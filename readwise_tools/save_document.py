"""rwr-save — save a URL to Readwise Reader (POST /save/)."""
from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit


@call_parse
def main(
    url: str,                  # the URL to save (e.g. an open.spotify.com episode URL)
    tags: str = "",             # comma-separated tags to attach
    location: str = "",         # target location: new|later|shortlist|archive|feed
):
    "Save a URL to Reader. Idempotent-by-url: an already-known URL returns the existing doc."
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    res = ReaderClient().save(url, tags=tag_list or None, location=location or None)
    emit(res)
