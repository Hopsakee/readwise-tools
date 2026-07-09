"""rw-books — list classic Readwise "book" records (GET /api/v2/books/).

Different product/API from `rwr-list` (Reader inbox). Classic Readwise is
where Snipd podcast highlights land; each book carries `num_highlights`
(always >= 1 by construction — a book only exists here if it has a highlight).
"""
from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit

DEFAULT_FIELDS = "id,title,author,category,source,source_url,highlights_url,num_highlights,updated"


@call_parse
def main(
    category: str = "",             # server-side category filter (podcasts, books, articles, ...)
    updated_after: str = "",        # ISO-8601 updated__gt cutoff
    limit: int = 0,                 # cap on total books returned (0 = no cap)
    fields: str = DEFAULT_FIELDS,   # comma-separated fields to emit; "all" for full records
):
    "List classic-Readwise book records as a JSON array."
    books = ReaderClient().fetch_rw_books(
        category=category or None,
        updated_after=updated_after or None,
        limit=limit or None,
    )
    if fields.strip().lower() == "all":
        emit(books)
    else:
        keys = [f.strip() for f in fields.split(",") if f.strip()]
        emit([{k: b.get(k) for k in keys} for b in books])
