"""rwr-move — move a document to another Reader location."""
import sys

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit

VALID_LOCATIONS = {"new", "later", "archive", "feed"}


@call_parse
def main(
    doc_id: str,     # the Reader document id to move
    location: str,   # target location: new|later|archive|feed
):
    "Move a document to a new location (PATCH /update/<id>/)."
    if location not in VALID_LOCATIONS:
        emit({"error": "invalid location", "location": location,
              "valid": sorted(VALID_LOCATIONS)})
        sys.exit(2)
    res = ReaderClient().move(doc_id, location)
    emit({"id": doc_id, "location": res.get("location", location), "ok": True, "raw": res})
