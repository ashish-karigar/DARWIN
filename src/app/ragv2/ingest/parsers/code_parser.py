from hashlib import sha256
from pathlib import Path

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source


LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sql": "sql",
    ".sh": "shell",
    ".zsh": "shell",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}


class CodeParser:
    """Loads source-code files without destroying their formatting."""

    name = "code"
    supported_extensions = frozenset(LANGUAGES)

    def __init__(
        self,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings

    def supports(self, source: Source) -> bool:
        source_text = str(source)

        if source_text.startswith(("http://", "https://")):
            return False

        return Path(source).suffix.lower() in self.supported_extensions

    def parse(self, source: Source) -> ParsedDocument:
        path = Path(source).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"{path} is not a file")

        max_bytes = self.settings.maximum_file_size_mb * 1024 * 1024

        if path.stat().st_size > max_bytes:
            raise ValueError(
                f"Code file exceeds "
                f"{self.settings.maximum_file_size_mb} MB"
            )

        code = path.read_text(
            encoding=self.settings.default_encoding
        )

        if not code.strip():
            raise ValueError(f"Code file is empty: {path}")

        source_uri = str(path)
        document_id = sha256(source_uri.encode("utf-8")).hexdigest()
        section_id = sha256(
            f"{document_id}:source".encode("utf-8")
        ).hexdigest()

        return ParsedDocument(
            document_id=document_id,
            title=path.name,
            source_type=SourceType.CODE,
            source_uri=source_uri,
            sections=(
                DocumentSection(
                    section_id=section_id,
                    text=code,
                    heading_path=(path.name,),
                    start_offset=0,
                    end_offset=len(code),
                ),
            ),
            metadata={
                "parser": self.name,
                "parser_version": "1.0",
                "language": LANGUAGES[path.suffix.lower()],
                "file_size_bytes": path.stat().st_size,
            },
        )