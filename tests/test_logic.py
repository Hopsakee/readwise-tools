"""Pure-logic tests — no network, no LLM. Run: uv run python tests/test_logic.py

Covers the deterministic helpers behind rw-prompt / rwr-tag / rwr-rate /
rwr-rate-tag / rwr-update. The live-inference paths (Inference.ts -> claude)
are verified out-of-session (the cron / a normal shell), never here.
"""
from readwise_tools.client import ReaderClient, tag_names
from readwise_tools.infer import extract_json
from readwise_tools.prompt_sync import strip_frontmatter
from readwise_tools.rate_tag import to_markdown
from readwise_tools.tag_document import parse_tags
from readwise_tools.update_document import _parse_tags

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed += 1
        print(f"FAIL  {name}\n      got:  {got!r}\n      want: {want!r}")


# --- strip_frontmatter -------------------------------------------------------
check("strip_frontmatter removes block",
      strip_frontmatter("---\na: 1\n---\nbody text\nmore"), "body text\nmore")
check("strip_frontmatter no-frontmatter unchanged",
      strip_frontmatter("just a body\nline2"), "just a body\nline2")

# --- parse_tags (rwr-tag) -----------------------------------------------------
check("parse_tags lowercases topic, keeps BOM_",
      parse_tags("#Productivity #communication #BOM_Progress"),
      ["productivity", "communication", "BOM_Progress"])
check("parse_tags empty", parse_tags("no hashes here"), [])

# --- _parse_tags (rwr-update) -------------------------------------------------
check("_parse_tags comma+space", _parse_tags("a, b  c,d"), ["a", "b", "c", "d"])

# --- extract_json ------------------------------------------------------------
check("extract_json plain", extract_json('{"TIER":"A"}'), {"TIER": "A"})
check("extract_json fenced",
      extract_json('```json\n{"TIER":"S"}\n```'), {"TIER": "S"})
check("extract_json with think + prose",
      extract_json('<think>hmm</think>\nHere: {"TIER":"B","x":1} done'),
      {"TIER": "B", "x": 1})

# --- to_markdown (orchestrator notes) ----------------------------------------
check("to_markdown nested",
      to_markdown({"TIER": "A", "IVs": [{"d": 3}]}),
      "**TIER:** A\n**IVs:**\n  -\n    **d:** 3")

# --- tag_names (dict + list shapes) ------------------------------------------
check("tag_names dict shape",
      tag_names({"tags": {"python": {}, "_rating/s/claude-haiku": {}}}),
      ["python", "_rating/s/claude-haiku"])
check("tag_names list shape",
      tag_names({"tags": ["a", {"name": "b"}]}), ["a", "b"])
check("tag_names absent", tag_names({}), [])

# --- ReaderClient.update body construction (monkeypatched _call) -------------
captured = {}


class FakeClient(ReaderClient):
    def __init__(self):
        pass  # skip token/session

    def _call(self, method, path, kind, **kw):
        captured["method"] = method
        captured["json"] = kw.get("json")
        return {"ok": True}


fc = FakeClient()
fc.update("abc123", tags=["x"], location="later")
check("update sends only provided fields (no notes key)",
      sorted(captured["json"].keys()), ["location", "tags"])
check("update method is PATCH", captured["method"], "PATCH")
fc.update("abc123", notes="hi")
check("update notes-only", captured["json"], {"notes": "hi"})
check("update empty no-op returns {}", fc.update("abc123"), {})

# --- save() body construction + path (H1: podcast-highlight-lane) -----------
fc.save("https://open.spotify.com/episode/abc123")
check("save path", captured.get("json"), {"url": "https://open.spotify.com/episode/abc123"})
check("save method is POST", captured["method"], "POST")
fc.save("https://x.example/y", tags=["podcast"], location="new")
check("save with tags+location",
      captured["json"],
      {"url": "https://x.example/y", "tags": ["podcast"], "location": "new"})

# --- fetch_rw_books() pagination + absolute-URL _call (H1) ------------------
pages = [
    {"results": [{"id": 1, "category": "podcasts"}], "next": "https://readwise.io/api/v2/books/?page=2"},
    {"results": [{"id": 2, "category": "podcasts"}], "next": None},
]


class PagedFakeClient(ReaderClient):
    def __init__(self):
        self._calls = []

    def _call(self, method, path, kind, **kw):
        self._calls.append((method, path, kw.get("params")))
        return pages[len(self._calls) - 1]


pfc = PagedFakeClient()
books = pfc.fetch_rw_books(category="podcasts")
check("fetch_rw_books collects both pages", [b["id"] for b in books], [1, 2])
check("fetch_rw_books first call hits /api/v2/books/", pfc._calls[0][1], "https://readwise.io/api/v2/books/")
check("fetch_rw_books first call sends category param", pfc._calls[0][2], {"page_size": 100, "category": "podcasts"})
check("fetch_rw_books follows `next` verbatim (no re-added params)",
      (pfc._calls[1][1], pfc._calls[1][2]),
      ("https://readwise.io/api/v2/books/?page=2", None))

pfc2 = PagedFakeClient()
check("fetch_rw_books respects limit", len(pfc2.fetch_rw_books(limit=1)), 1)

# --- rate_text tier validation (H2 fix) — stub the LLM call ----------------
import readwise_tools.rate_document as rd

rd.run_inference = lambda system, user, level="fast": '{"TIER":"A","ROI":"7/10"}'
check("rate_text valid tier", rd.rate_text("text", prompt_body="P")["tier"], "A")

rd.run_inference = lambda system, user, level="fast": '{"TIER":"A/B excellent"}'
got = rd.rate_text("text", prompt_body="P")
check("rate_text rejects malformed tier (no junk tag)", "error" in got and "tier" not in got, True)

rd.run_inference = lambda system, user, level="fast": "not json at all"
check("rate_text non-json -> error", "error" in rd.rate_text("text", prompt_body="P"), True)
check("rate_text empty text -> error", "error" in rd.rate_text("", prompt_body="P"), True)

# --- fetch_rw_book_highlights: pagination + book_id param --------------------
class PagingClient(ReaderClient):
    """Stub _call to return two DRF pages, capturing the calls made."""

    def __init__(self):
        self.calls = []
        self._pages = [
            {"results": [{"id": 1, "text": "h1"}, {"id": 2, "text": "h2"}],
             "next": "https://readwise.io/api/v2/highlights/?book_id=99&page=2"},
            {"results": [{"id": 3, "text": "h3"}], "next": None},
        ]

    def _call(self, method, path, kind, **kw):
        self.calls.append({"method": method, "path": path, "params": kw.get("params")})
        return self._pages[len(self.calls) - 1]


pc = PagingClient()
hs = pc.fetch_rw_book_highlights(99)
check("fetch_rw_book_highlights follows next across pages", [h["id"] for h in hs], [1, 2, 3])
check("fetch_rw_book_highlights sends book_id as a query param (not path)",
      pc.calls[0]["params"], {"book_id": 99, "page_size": 100})
check("fetch_rw_book_highlights hits the classic /highlights/ endpoint",
      pc.calls[0]["path"].endswith("/api/v2/highlights/"), True)
check("fetch_rw_book_highlights drops params on the follow-up page (next carries them)",
      pc.calls[1]["params"], None)

pc2 = PagingClient()
pc2._pages = [{"results": [{"id": 1, "text": "h1"}, {"id": 2, "text": "h2"}], "next": None}]
check("fetch_rw_book_highlights honors limit", len(pc2.fetch_rw_book_highlights(1, limit=1)), 1)

pc3 = PagingClient()
pc3._pages = [{"results": [], "next": None}]
check("fetch_rw_book_highlights returns [] for a book with no highlights",
      pc3.fetch_rw_book_highlights(7), [])

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
