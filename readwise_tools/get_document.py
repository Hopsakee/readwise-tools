"""rw-get — fetch one document's metadata plus transcript (html or plain text)."""
import json
import sys

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, html_to_text


@call_parse
def main(
    doc_id: str,                    # the Reader document id
    text: bool = False,             # emit transcript as stripped plain text instead of html_content
    keep_timestamps: bool = False,  # with --text, keep [0:00]-style timestamps (default: strip)
):
    "Get a single document's metadata + transcript as JSON."
    client = ReaderClient()
    doc = client.get(doc_id, with_html=True)
    if not doc:
        print(json.dumps({"error": "not found", "id": doc_id}))
        sys.exit(1)
    if text:
        out = {k: v for k, v in doc.items() if k != "html_content"}
        out["text"] = html_to_text(doc.get("html_content", ""), strip_timestamps=not keep_timestamps)
        doc = out
    print(json.dumps(doc, ensure_ascii=False, indent=2))
