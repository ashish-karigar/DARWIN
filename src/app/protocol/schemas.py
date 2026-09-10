from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


PROTOCOL_VERSION = "1.0"


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WindowBounds(ProtocolModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class WindowState(ProtocolModel):
    instance_id: UUID = Field(alias="instanceId")
    bounds: WindowBounds
    restore_bounds: WindowBounds | None = Field(default=None, alias="restoreBounds")
    mode: Literal["normal", "minimized", "maximized"]
    focused: bool
    z_index: int = Field(alias="zIndex", ge=0)


class AppManifest(ProtocolModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$", max_length=128)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=160)
    version: str = Field(min_length=1, max_length=32)
    type: Literal["native", "web", "external"]
    icon: str | None = None
    entry: str | None = None
    url: str | None = None
    allowed_origins: list[str] = Field(default_factory=list, alias="allowedOrigins")
    permissions: list[str] = Field(default_factory=list)
    session: str | None = None
    instance_policy: Literal["single", "multiple"] = Field(
        default="single", alias="instancePolicy"
    )
    pinned: bool = False
    launcher_order: int = Field(default=100, alias="launcherOrder", ge=0)
    display_mode: Literal["window", "fullscreen"] = Field(
        default="window", alias="displayMode"
    )

    @model_validator(mode="after")
    def validate_entrypoint(self) -> "AppManifest":
        if self.type == "native" and not self.entry:
            raise ValueError("Native apps require an entry.")
        if self.type == "web" and not self.url:
            raise ValueError("Web apps require a URL.")
        if self.type == "web" and not self.session:
            raise ValueError("Web apps require an isolated session.")
        if self.type == "web" and not self.allowed_origins:
            raise ValueError("Web apps require at least one approved origin.")
        if self.type == "web" and self.url:
            initial = urlparse(self.url)
            approved = any(
                (parsed := urlparse(origin)).scheme == "https"
                and parsed.netloc == initial.netloc
                for origin in self.allowed_origins
            )
            if initial.scheme != "https" or not approved:
                raise ValueError("Web app URL must use an approved HTTPS origin.")
        return self


class AppInstance(ProtocolModel):
    id: UUID
    app_id: str = Field(alias="appId")
    launched_at: datetime = Field(alias="launchedAt")
    status: Literal["launching", "running", "suspended", "error", "closed"]
    window_id: UUID | None = Field(alias="windowId")
    error: str | None = Field(default=None, max_length=500)


InputSource = Literal[
    "mouse", "keyboard", "voice", "gesture", "gamepad", "remote", "system"
]


class InputEvent(ProtocolModel):
    source: InputSource
    timestamp: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class PointerMoveEvent(InputEvent):
    type: Literal["pointer.move"]
    x: float
    y: float


class PointerClickEvent(InputEvent):
    type: Literal["pointer.click"]
    button: Literal["left", "middle", "right"]
    action: Literal["down", "up", "click"]


class NavigationEvent(InputEvent):
    type: Literal["navigation"]
    action: Literal["back", "forward", "home", "select", "cancel", "next", "previous"]


class TextInputEvent(InputEvent):
    type: Literal["text"]
    text: str = Field(max_length=10_000)


class MediaInputEvent(InputEvent):
    type: Literal["media"]
    action: Literal["play", "pause", "toggle", "stop", "seek-forward", "seek-backward"]


class CommandInputEvent(InputEvent):
    type: Literal["command"]
    command: str = Field(min_length=1, max_length=2_000)


DarwinInputEvent = Annotated[
    PointerMoveEvent
    | PointerClickEvent
    | NavigationEvent
    | TextInputEvent
    | MediaInputEvent
    | CommandInputEvent,
    Field(discriminator="type"),
]

darwin_input_event_adapter = TypeAdapter(DarwinInputEvent)


class WireMessage(ProtocolModel):
    protocol_version: str = Field(alias="protocolVersion")
    message_id: UUID = Field(alias="messageId")
    timestamp: datetime

    @model_validator(mode="after")
    def validate_protocol_version(self) -> "WireMessage":
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError(
                f"Unsupported protocol version: {self.protocol_version}. "
                f"Expected {PROTOCOL_VERSION}."
            )
        return self


class SessionHello(WireMessage):
    type: Literal["session.hello"]
    client_name: str = Field(alias="clientName", min_length=1, max_length=80)


class AssistantRequest(WireMessage):
    type: Literal["assistant.request"]
    session_id: str = Field(alias="sessionId", min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=50_000)


class AssistantCancel(WireMessage):
    type: Literal["assistant.cancel"]
    request_id: UUID = Field(alias="requestId")


class ConfirmationResponse(WireMessage):
    type: Literal["confirmation.response"]
    request_id: UUID = Field(alias="requestId")
    approved: bool


ClientMessage = Annotated[
    SessionHello | AssistantRequest | AssistantCancel | ConfirmationResponse,
    Field(discriminator="type"),
]

client_message_adapter = TypeAdapter(ClientMessage)


class SessionReady(WireMessage):
    type: Literal["session.ready"]
    backend_version: str = Field(alias="backendVersion")
    accepted_protocol_version: str = Field(alias="acceptedProtocolVersion")


class AssistantState(WireMessage):
    type: Literal["assistant.state"]
    request_id: UUID | None = Field(alias="requestId")
    state: Literal[
        "idle", "listening", "transcribing", "thinking", "speaking", "error"
    ]


class AssistantResponse(WireMessage):
    type: Literal["assistant.response"]
    request_id: UUID = Field(alias="requestId")
    content: str = Field(max_length=100_000)
    final: bool


class ConfirmationRequired(WireMessage):
    type: Literal["confirmation.required"]
    request_id: UUID = Field(alias="requestId")
    summary: str = Field(min_length=1, max_length=1_000)
    risk: Literal["low", "reversible_write", "destructive", "sensitive"]
    expires_at: datetime = Field(alias="expiresAt")


class ErrorMessage(WireMessage):
    type: Literal["error"]
    request_id: UUID | None = Field(alias="requestId")
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=1_000)
    recoverable: bool
    details: dict[str, object] | None = None


ServerMessage = Annotated[
    SessionReady
    | AssistantState
    | AssistantResponse
    | ConfirmationRequired
    | ErrorMessage,
    Field(discriminator="type"),
]

server_message_adapter = TypeAdapter(ServerMessage)
