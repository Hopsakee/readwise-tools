"""rwr-rate — rate a document's reading-ROI tier (S/A/B/C/D) by a given prompt.

Sources the document text from a Reader id (--id, via the client) or from a
file / stdin (--text-file), loads the quality prompt from the prompts-sync
library (default `estimate-quality`), asks the model (Inference.ts, default
fast=Haiku) to return its strict JSON verdict, and extracts the TIER.

Returns a clean JSON object — never a traceback — so it is safe to call in an
unattended batch.
"""
from __future__ import annotations

import sys

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit, html_to_text
from readwise_tools.infer import extract_json, run_inference
from readwise_tools.prompt_sync import load_prompt


def rate_text(
    text: str,
    prompt_name: str = "estimate-quality",
    level: str = "fast",
    model_slug: str = "claude-haiku",
    prompt_body: str | None = None,
    repo: str | None = None,
    pull: bool = True,
) -> dict:
    """Rate `text` and return {tier, model, quality} or {error, model}.

    `prompt_body` lets a batch caller load the prompt once and reuse it instead
    of re-pulling the repo per item.
    """
    if not text or not text.strip():
        return {"error": "empty document text", "model": model_slug}
    system = prompt_body if prompt_body is not None else load_prompt(
        prompt_name, repo=repo, pull=pull
    )
    try:
        raw = run_inference(system, text, level=level)
        quality = extract_json(raw)
    except Exception as e:  # noqa: BLE001 — batch-safe: surface, don't crash
        return {"error": str(e)[:300], "model": model_slug}
    tier = str(quality.get("TIER", "")).strip()
    # Validate BEFORE the tier is ever interpolated into the `_rating/<tier>/<model>`
    # tag: a malformed tier ("A/B", "Tier A", spaces) would corrupt cs-groundtruth's
    # rater parse. A bad tier sends the item to PROCESS_MANUAL instead of writing junk.
    if tier not in {"S", "A", "B", "C", "D"}:
        return {"error": f"invalid TIER {tier!r}", "model": model_slug, "quality": quality}
    return {"tier": tier, "model": model_slug, "quality": quality}


def _read_text_arg(text_file: str) -> str:
    if text_file == "-":
        return sys.stdin.read()
    from pathlib import Path
    return Path(text_file).expanduser().read_text(encoding="utf-8")


@call_parse
def main(
    id: str = "",            # Reader document id to fetch + rate
    text_file: str = "",     # read document text from this file ('-' = stdin) instead
    prompt: str = "estimate-quality",  # prompt name in the prompts-sync library
    level: str = "fast",     # inference level: fast|standard|smart
    model_slug: str = "claude-haiku",  # model component used in the _rating tag
    no_pull: bool = False,   # skip the prompt-repo git pull
):
    "Rate a document's reading-ROI tier (S/A/B/C/D) using a quality prompt."
    if not id and not text_file:
        emit({"error": "provide --id or --text-file"})
        sys.exit(2)
    if id:
        doc = ReaderClient().get(id, with_html=True)
        if not doc:
            emit({"error": "document not found", "id": id})
            sys.exit(2)
        text = html_to_text(doc.get("html_content", "")) or doc.get("summary", "")
    else:
        text = _read_text_arg(text_file)
    result = rate_text(text, prompt_name=prompt, level=level,
                       model_slug=model_slug, pull=not no_pull)
    if id:
        result["id"] = id
    emit(result)
    if "error" in result:
        sys.exit(1)
