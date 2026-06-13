"""Inference helper — the single sanctioned path to an LLM call.

Everything routes through `bun ~/.claude/PAI/TOOLS/Inference.ts` (the PAI
inference tool), never `@anthropic-ai/sdk` and never `claude --bare`.
`--level` chooses the model tier (fast=Haiku cheapest, standard=Sonnet,
smart=Opus); it is exposed as a flag everywhere so the future swap to a local
model is a one-flag change.

Two helpers:
  run_inference(system, user, level)  -> raw model text (str)
  extract_json(text)                  -> first JSON object found (dict)

`extract_json` is tolerant: it strips ```code fences and <think>…</think>
blocks (a reasoning model may emit them) and falls back to the outermost
{...} span, so a slightly chatty model response still parses.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

# Assembled from parts so no user-home literal is baked in for portability.
INFERENCE_TS = Path.home() / ".claude" / "PAI" / "TOOLS" / "Inference.ts"

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def run_inference(
    system: str,
    user: str,
    level: str = "fast",
    inference_timeout_ms: int = 180000,
) -> str:
    """Call Inference.ts and return the raw model text. Raises on failure.

    The document text is passed via Inference.ts's stdin (it reads the user
    prompt from stdin), so document size is not an ARG_MAX concern.

    We pass `--timeout` EXPLICITLY: Inference.ts defaults `fast`/Haiku to 15s,
    far too tight for the heavy `estimate-quality` rubric. MEASURED 2026-06-13:
    a ~9k-word (47KB) article through that rubric on Haiku takes ~108s. So the
    default is 180s (covers a near-10k-word doc with headroom); too-low a value
    silently downgrades rateable items to PROCESS_MANUAL. The outer subprocess
    timeout is kept strictly larger so the model deadline (not the wrapper)
    governs.
    """
    if not INFERENCE_TS.exists():
        raise RuntimeError(f"Inference.ts not found at {INFERENCE_TS}")
    timeout = inference_timeout_ms / 1000 + 30
    cmd = ["bun", str(INFERENCE_TS), "--level", level,
           "--timeout", str(inference_timeout_ms), system, user]
    # Inherit the environment; Inference.ts handles subscription-billing scrubbing.
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=os.environ.copy()
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Inference.ts (level={level}) failed: {proc.stderr.strip()[:300]}"
        )
    return proc.stdout.strip()


def extract_json(text: str) -> dict:
    """Best-effort parse of a JSON object out of a model response.

    Raises ValueError if no object can be recovered.
    """
    if not text:
        raise ValueError("empty response")
    s = _THINK_RE.sub("", text).strip()
    s = _FENCE_RE.sub("", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fallback: outermost {...} span.
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return json.loads(s[start : end + 1])
    raise ValueError("no JSON object found in response")
