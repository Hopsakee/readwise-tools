"""rw-list — list Readwise Reader documents in a location, optionally filtered."""
import json

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient

DEFAULT_FIELDS = "id,title,author,category,source_url,url,site_name,word_count,created_at"


@call_parse
def main(
    location: str = "new",          # Reader location: new|later|shortlist|archive|feed
    category: str = "",             # optional category filter (e.g. podcast, article, video)
    domain: str = "",               # optional client-side substring filter on source_url/url
    updated_after: str = "",        # optional ISO-8601 updatedAfter cutoff
    limit: int = 0,                 # cap on total documents returned (0 = no cap)
    fields: str = DEFAULT_FIELDS,   # comma-separated fields to emit; "all" for full docs
):
    "List Reader documents as a JSON array (id + metadata)."
    client = ReaderClient()
    docs = client.list(
        location=location or None,
        category=category or None,
        updated_after=updated_after or None,
        domain=domain or None,
        limit=limit or None,
    )
    if fields.strip().lower() == "all":
        slim = docs
    else:
        keys = [f.strip() for f in fields.split(",") if f.strip()]
        slim = [{k: d.get(k) for k in keys} for d in docs]
    print(json.dumps(slim, ensure_ascii=False, indent=2))
