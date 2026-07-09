"""rwr-tag — assign topic tags to a document from a fixed-vocabulary prompt.

Duplicate-tag prevention is structural: the `add-topic-tags` prompt embeds the
full controlled vocabulary, so the model can only choose from existing tags —
it can't invent near-duplicates. `--existing-tags` / `--vocab-file` optionally
appends an extra constraint line (e.g. the live set of tags already in use) for
callers who want to reinforce or extend the vocabulary at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastcore.script import call_parse

from readwise_tools.client import ReaderClient, emit, html_to_text
from readwise_tools.infer import run_inference
from readwise_tools.prompt_sync import load_prompt


def parse_tags(response: str) -> list[str]:
    """Parse a `#tag #tag` model response into a clean tag list.

    Splits on '#', strips whitespace, drops empties. Lowercases plain topic
    tags but preserves the BOM_ prefix casing the prompt mandates.
    """
    out = []
    for chunk in response.split("#")[1:]:
        tag = chunk.strip().split()[0] if chunk.strip() else ""
        if not tag:
            continue
        out.append(tag if tag.startswith("BOM_") else tag.lower())
    return out


def tag_text(
    text: str,
    prompt_name: str = "add-topic-tags",
    level: str = "fast",
    existing_tags: list[str] | None = None,
    prompt_body: str | None = None,
    repo: str | None = None,
    pull: bool = True,
) -> list[str]:
    """Return the list of topic tags for `text`. Empty text -> empty list."""
    if not text or not text.strip():
        return []
    system = prompt_body if prompt_body is not None else load_prompt(
        prompt_name, repo=repo, pull=pull
    )
    if existing_tags:
        system += (
            "\n\nPrefer reusing these already-existing tags when applicable, "
            "to avoid creating near-duplicates: " + " ".join(sorted(set(existing_tags)))
        )
    raw = run_inference(system, text, level=level)
    return parse_tags(raw)


@call_parse
def main(
    id: str = "",            # Reader document id to fetch + tag
    text_file: str = "",     # read document text from this file ('-' = stdin) instead
    prompt: str = "add-topic-tags",  # prompt name in the prompts-sync library
    level: str = "fast",     # inference level: fast|standard|smart
    vocab_file: str = "",    # file of extra existing tags to reinforce (one per line / space-sep)
    no_pull: bool = False,   # skip the prompt-repo git pull
):
    "Assign topic tags to a document from the fixed-vocabulary tag prompt."
    if not id and not text_file:
        emit({"error": "provide --id or --text-file"})
        sys.exit(2)
    existing = None
    if vocab_file:
        existing = Path(vocab_file).expanduser().read_text().replace(",", " ").split()
    if id:
        doc = ReaderClient().get(id, with_html=True)
        if not doc:
            emit({"error": "document not found", "id": id})
            sys.exit(2)
        text = html_to_text(doc.get("html_content", "")) or doc.get("summary", "")
    else:
        text = sys.stdin.read() if text_file == "-" else Path(text_file).expanduser().read_text()
    tags = tag_text(text, prompt_name=prompt, level=level,
                    existing_tags=existing, pull=not no_pull)
    emit(tags)
