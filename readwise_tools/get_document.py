"""rw-get — fetch one document's metadata plus transcript (html or plain text)."""
import sys

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit, html_to_text


@call_parse
def main(
    doc_id: str,                    # the Reader document id
    text: bool = False,             # emit transcript as stripped plain text instead of html_content
    keep_timestamps: bool = False,  # with --text, keep [0:00]-style timestamps (default: strip)
):
    "Get a single document's metadata + transcript as JSON."
    doc = ReaderClient().get(doc_id, with_html=True)
    if not doc:
        emit({"error": "not found", "id": doc_id})
        sys.exit(1)
    if text:
        plain = html_to_text(doc.get("html_content", ""), strip_timestamps=not keep_timestamps)
        doc = {k: v for k, v in doc.items() if k != "html_content"}
        doc["text"] = plain
    emit(doc)
