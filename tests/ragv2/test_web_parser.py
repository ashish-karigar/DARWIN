import httpx
import pytest

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.web_parser import WebParser


HTML = """
<html>
  <head>
    <title>DARWIN Architecture</title>
    <meta name="description" content="DARWIN RAG documentation">
  </head>
  <body>
    <nav>Navigation that should not matter</nav>
    <main>
      <h1>DARWIN Architecture</h1>
      <p>
        DARWIN uses retrieval-augmented generation to answer questions
        using information retrieved from trusted documents.
      </p>
      <p>
        Hybrid retrieval combines semantic vector search with lexical
        keyword search to improve retrieval quality.
      </p>
    </main>
  </body>
</html>
"""


def create_client(
    status_code: int = 200,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            text=HTML,
            headers={"content-type": "text/html"},
            request=request,
        )

    return httpx.Client(
        transport=httpx.MockTransport(handler)
    )


def test_supports_web_urls():
    parser = WebParser()

    assert parser.supports("https://example.com/document")
    assert parser.supports("http://example.com")
    assert not parser.supports("document.txt")


def test_parses_web_page():
    with create_client() as client:
        document = WebParser(http_client=client).parse(
            "https://example.com/document"
        )

    combined_text = " ".join(
        section.text for section in document.sections
    )

    assert document.title == "DARWIN Architecture"
    assert document.source_type == SourceType.WEB
    assert document.source_uri == "https://example.com/document"
    assert "retrieval-augmented generation" in combined_text
    assert "Hybrid retrieval" in combined_text
    assert document.metadata["parser"] == "web"


def test_web_error_is_reported():
    with create_client(status_code=404) as client:
        parser = WebParser(http_client=client)

        with pytest.raises(httpx.HTTPStatusError):
            parser.parse("https://example.com/missing")