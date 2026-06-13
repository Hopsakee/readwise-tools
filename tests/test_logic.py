"""Pure-logic tests — no network, no LLM. Run: uv run python tests/test_logic.py

Covers the deterministic helpers behind rw-prompt / rw-tag / rw-rate /
rw-rate-tag / rw-update. The live-inference paths (Inference.ts -> claude) are
verified out-of-session (the cron / a normal shell), never here.
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

# --- parse_tags (rw-tag) -----------------------------------------------------
check("parse_tags lowercases topic, keeps BOM_",
      parse_tags("#Productivity #communication #BOM_Progress"),
      ["productivity", "communication", "BOM_Progress"])
check("parse_tags empty", parse_tags("no hashes here"), [])

# --- _parse_tags (rw-update) -------------------------------------------------
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

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
