"""rwr-update — modify a Reader document: tags, notes, and/or location.

The "modify" half of "read and modify items in Readwise Reader" (the "read"
half is rwr-list / rwr-get). Only the flags you pass are sent in the PATCH, so
`rwr-update <id> --location archive` won't disturb tags or notes.
"""
import sys

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit

VALID_LOCATIONS = {"new", "later", "archive", "feed"}


def _parse_tags(raw: str) -> list[str]:
    """Split a `--tags` value on commas/whitespace into a clean list."""
    return [t for t in raw.replace(",", " ").split() if t]


@call_parse
def main(
    doc_id: str,          # the Reader document id to modify
    tags: str = "",       # space/comma-separated tag list (replaces the doc's tags)
    notes: str = "",      # notes/markdown body to set
    location: str = "",   # new|later|archive|feed
    set_empty_notes: bool = False,  # allow setting notes to an empty string explicitly
):
    "Modify a Reader document (PATCH /update/<id>/) — only provided fields are sent."
    if location and location not in VALID_LOCATIONS:
        emit({"error": "invalid location", "location": location,
              "valid": sorted(VALID_LOCATIONS)})
        sys.exit(2)
    kw: dict = {}
    if tags:
        kw["tags"] = _parse_tags(tags)
    if notes or set_empty_notes:
        kw["notes"] = notes
    if location:
        kw["location"] = location
    if not kw:
        emit({"error": "nothing to update", "hint": "pass --tags, --notes, and/or --location"})
        sys.exit(2)
    res = ReaderClient().update(doc_id, **kw)
    emit({"id": doc_id, "ok": True, "sent": sorted(kw.keys()), "raw": res})
