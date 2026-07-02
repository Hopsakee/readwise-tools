"""rw-rate-tag — the nightly orchestrator (faithful n8n "Rate and tag sources").

Pipeline, per the dead n8n workflow:
  1. fetch location=new items (with html), capped by --limit
  2. skip items already carrying a _rating/ tag (idempotency beyond new->later)
  3. word_count > 10000 (or empty text)  -> tag PROCESS_MANUAL, move to later, skip LLM
  4. otherwise: html->text, rate (quality tier) + tag (topic tags)
  5. tags = topic tags + `_rating/<TIER>/<model-slug>`; notes = quality JSON as markdown
  6. write back: tags + notes + location=later
  7. feed consume-selection: cs-ingest (later+new) + cs-groundtruth (later)

Safety: the LLM is only ever called for items that pass the gate AND within
--limit, so cost is bounded. Per-item errors are isolated — one bad document is
flagged PROCESS_MANUAL and the batch continues.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit, html_to_text, tag_names
from readwise_tools.prompt_sync import load_prompt
from readwise_tools.rate_document import rate_text
from readwise_tools.tag_document import tag_text

# Repo was renamed consume-selection -> l-space-librarian on 2026-07-02. The old
# path no longer exists; `uv run --project <gone>` failed silently (ERR log line,
# rate_tag still exit 0), so the nightly Readwise -> l-space.db feed had stopped.
CONSUME_SELECTION_REPO = Path.home() / "Code" / "l-space-librarian"
MAX_WORDS = 10000


def to_markdown(obj, indent: int = 0) -> str:
    """Render a (possibly nested) quality JSON object as readable markdown.

    Direct port of the n8n `toMarkdown` JS helper so the notes block matches
    the historical format exactly.
    """
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(to_markdown(item, indent + 1))
            else:
                lines.append(f"{pad}- {item}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}**{key}:**")
                lines.append(to_markdown(value, indent + 1))
            else:
                lines.append(f"{pad}**{key}:** {value}")
    else:
        lines.append(f"{pad}{obj}")
    return "\n".join(lines)


def _already_rated(doc: dict) -> bool:
    return any(t.startswith("_rating/") or t.startswith("rating/") for t in tag_names(doc))


def _feed_consume_selection(repo: Path) -> list[str]:
    """Run cs-ingest (later+new) + cs-groundtruth (later). Returns log lines."""
    log = []
    steps = [
        ["cs-ingest", "--location", "later"],
        ["cs-ingest", "--location", "new"],
        ["cs-groundtruth", "--location", "later"],
    ]
    for step in steps:
        cmd = ["uv", "run", "--project", str(repo), *step]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            ok = r.returncode == 0
            log.append(f"{'ok ' if ok else 'ERR'} {' '.join(step)}: {(r.stdout or r.stderr).strip()[:160]}")
        except Exception as e:  # noqa: BLE001
            log.append(f"ERR {' '.join(step)}: {str(e)[:160]}")
    return log


@call_parse
def main(
    limit: int = 10,         # max items to process per run (scheduled run uses 10)
    location: str = "new",   # Reader location to drain
    level: str = "fast",     # inference level: fast|standard|smart
    model_slug: str = "claude-haiku",  # model component of the _rating tag
    quality_prompt: str = "estimate-quality",
    tags_prompt: str = "add-topic-tags",
    dry_run: bool = False,   # rate+tag but print planned PATCH instead of writing
    no_feed: bool = False,   # skip the consume-selection ingest/groundtruth feed
    no_pull: bool = False,   # skip the prompt-repo git pull
):
    "Rate + tag new Reader items, write back, and feed consume-selection."
    # Cost guard: refuse an unbounded run. `--limit 0` (the "unlimited" convention
    # elsewhere) would unleash 2 LLM calls per item across the whole inbox — exactly
    # what this guard exists to prevent. The scheduled wrapper always passes 10.
    if limit < 1:
        emit({"error": "refusing unbounded run", "hint": "pass --limit >= 1 (scheduled run uses 10)"})
        sys.exit(2)
    client = ReaderClient()
    docs = client.fetch(location=location, with_html=True, limit=limit or None)

    # Load each prompt ONCE (pull the repo once), reuse the body per item.
    q_body = load_prompt(quality_prompt, pull=not no_pull)
    t_body = load_prompt(tags_prompt, pull=False)  # already pulled above

    processed = manual = skipped = errors = 0
    results = []
    for doc in docs:
        doc_id = doc.get("id")
        if not doc_id:
            continue
        if _already_rated(doc):
            skipped += 1
            continue
        wc = doc.get("word_count") or 0
        text = html_to_text(doc.get("html_content", "")) or (doc.get("summary") or "")

        # Gate: too long or no text -> PROCESS_MANUAL, leave the LLM untouched.
        if (isinstance(wc, int) and wc > MAX_WORDS) or not text.strip():
            manual += 1
            results.append({"id": doc_id, "action": "PROCESS_MANUAL", "word_count": wc})
            if not dry_run:
                client.update(doc_id, tags=["PROCESS_MANUAL"], location="later")
            continue

        try:
            rated = rate_text(text, level=level, model_slug=model_slug, prompt_body=q_body)
            if "error" in rated:
                raise RuntimeError(rated["error"])
            tier = rated["tier"]
            topic_tags = tag_text(text, level=level, prompt_body=t_body)
            tags = topic_tags + [f"_rating/{tier}/{model_slug}"]
            notes = to_markdown(rated["quality"])
        except Exception as e:  # noqa: BLE001 — isolate per-item failure
            errors += 1
            results.append({"id": doc_id, "action": "ERROR->PROCESS_MANUAL", "error": str(e)[:200]})
            if not dry_run:
                client.update(doc_id, tags=["PROCESS_MANUAL"], location="later")
            continue

        processed += 1
        plan = {"id": doc_id, "title": (doc.get("title") or "")[:60],
                "tier": tier, "tags": tags, "notes_chars": len(notes)}
        results.append(plan)
        if not dry_run:
            client.update(doc_id, tags=tags, notes=notes, location="later")

    feed_log = []
    if not dry_run and not no_feed and processed + manual > 0:
        feed_log = _feed_consume_selection(CONSUME_SELECTION_REPO)

    # Root cause of the silent-feed outage: feed failures were only ERR log
    # lines while `errors` (which the nightly wrapper alarms on) stayed 0, so a
    # broken feed produced a clean-looking run. Roll feed failures into errors
    # so the wrapper's ERRORS>0 alarm fires. (audit 2026-07-02)
    feed_errors = sum(1 for line in feed_log if line.startswith("ERR"))
    errors += feed_errors

    emit({
        "dry_run": dry_run,
        "seen": len(docs),
        "processed": processed,
        "process_manual": manual,
        "skipped_already_rated": skipped,
        "errors": errors,
        "feed_errors": feed_errors,
        "results": results,
        "consume_selection_feed": feed_log,
    })
