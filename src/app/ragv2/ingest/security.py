import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeSourceURLError(ValueError):
    """Raised when a web source could reach a protected network target."""


AddressResolver = Callable[[str, int], Iterable[str]]


def resolve_host(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname without making an HTTP request."""

    records = socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    return tuple(
        dict.fromkeys(record[4][0] for record in records)
    )


@dataclass(frozen=True, slots=True)
class URLSafetyPolicy:
    """Allows public HTTP sources while blocking SSRF destinations."""

    resolver: AddressResolver = resolve_host

    BLOCKED_HOSTNAMES = frozenset(
        {
            "localhost",
            "localhost.localdomain",
            "metadata.google.internal",
        }
    )
    BLOCKED_SUFFIXES = (".local", ".internal", ".localhost")

    def validate(self, url: str) -> str:
        parsed = urlsplit(url)
        self._validate_structure(parsed)

        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if (
            hostname in self.BLOCKED_HOSTNAMES
            or hostname.endswith(self.BLOCKED_SUFFIXES)
        ):
            raise UnsafeSourceURLError(
                f"Web source hostname is not public: {hostname}"
            )

        addresses = self._addresses(hostname, port)
        if not addresses:
            raise UnsafeSourceURLError(
                f"Web source hostname did not resolve: {hostname}"
            )

        blocked = tuple(
            str(address)
            for address in addresses
            if not address.is_global
        )
        if blocked:
            raise UnsafeSourceURLError(
                "Web source resolves to a protected address: "
                + ", ".join(blocked)
            )

        return self._normalized(parsed, hostname)

    @staticmethod
    def _validate_structure(parsed: SplitResult) -> None:
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeSourceURLError(
                "Only HTTP and HTTPS web sources are allowed."
            )

        if not parsed.hostname:
            raise UnsafeSourceURLError(
                "Web source must include a hostname."
            )

        if parsed.username is not None or parsed.password is not None:
            raise UnsafeSourceURLError(
                "Credentials are not allowed in web source URLs."
            )

        try:
            parsed.port
        except ValueError as error:
            raise UnsafeSourceURLError(
                "Web source contains an invalid port."
            ) from error

    def _addresses(
        self,
        hostname: str,
        port: int,
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        try:
            return (ipaddress.ip_address(hostname),)
        except ValueError:
            pass

        try:
            resolved = self.resolver(hostname, port)
        except (OSError, socket.gaierror) as error:
            raise UnsafeSourceURLError(
                f"Unable to resolve web source hostname: {hostname}"
            ) from error

        addresses = []
        for value in resolved:
            try:
                addresses.append(ipaddress.ip_address(value))
            except ValueError as error:
                raise UnsafeSourceURLError(
                    "Hostname resolver returned an invalid address."
                ) from error

        return tuple(dict.fromkeys(addresses))

    @staticmethod
    def _normalized(parsed: SplitResult, hostname: str) -> str:
        host = (
            f"[{hostname}]"
            if ":" in hostname
            else hostname
        )
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"

        return urlunsplit(
            (
                parsed.scheme.casefold(),
                host,
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
