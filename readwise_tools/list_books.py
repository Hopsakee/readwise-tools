"""rw-books — list classic Readwise (v2) "book" records (GET /api/v2/books/).

Different product/API from `rw-list` (Reader v3 inbox). Classic Readwise is
where Snipd podcast highlights land; each book carries `num_highlights`.
"""
from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit

DEFAULT_FIELDS = "id,title,author,category,source,source_url,highlights_url,num_highlights,updated"


@call_parse
def main(
    category: str = "",             # server-side category filter (podcasts, books, articles, ...)
    updated_after: str = "",        # ISO-8601 updated__gt cutoff
    limit: int = 0,                 # cap on total books returned (0 = no cap)
    min_highlights: int = 0,        # client-side filter: only books with >= N highlights
    fields: str = DEFAULT_FIELDS,   # comma-separated fields to emit; "all" for full records
):
    "List classic-Readwise book records as a JSON array."
    books = ReaderClient().fetch_v2_books(
        category=category or None,
        updated_after=updated_after or None,
        limit=limit or None,
        min_highlights=min_highlights,
    )
    if fields.strip().lower() == "all":
        emit(books)
    else:
        keys = [f.strip() for f in fields.split(",") if f.strip()]
        emit([{k: b.get(k) for k in keys} for b in books])
