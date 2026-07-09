# readwise-tools

Small, composable CLI tools over two distinct Readwise products/APIs — same
token, different bases. The prefix tells you which one a command hits:

- **`rwr-*`** — [Readwise Reader API](https://readwise.io/reader_api) (v3): the reading-inbox
  product (articles, videos, podcast transcripts). List/get/move/update documents.
- **`rw-*`** — classic Readwise API (v2): the highlights product (where Snipd podcast
  highlights land). `rw-books` lists highlighted sources; `rw-prompt` doesn't hit
  Readwise at all (it reads a local prompts-library clone) but keeps the `rw-` prefix
  since it's part of the same toolbox.

Built to feed a personal Library archive pipeline (Spotify-podcast transcripts → Library →
wiki/recall), but each tool is a standalone, pipe-friendly CLI that emits JSON to stdout.

## Install

```bash
uv sync            # create the venv and install the console scripts
```

Run via `uv run`:

```bash
uv run rwr-list --location new
uv run rwr-get <document_id> --text
uv run rwr-move <document_id> archive
```

## Token

The CLIs read your Readwise token at runtime and never print it. Resolution order:

1. `READWISE_TOKEN` environment variable
2. `READWISE_TOKEN_FILE` — path to a file containing the token
3. default file: `~/.config/readwise-tools/token`

Recommended setup (token stays out of git, out of your shell history):

```bash
mkdir -p ~/.config/readwise-tools
printf '%s' 'YOUR_TOKEN' > ~/.config/readwise-tools/token
chmod 600 ~/.config/readwise-tools/token
```

Get a token at <https://readwise.io/access_token>. See `.env.example` for details.

## Reader tools (`rwr-*`)

### `rwr-list` — list documents in a location

```bash
uv run rwr-list --location new
uv run rwr-list --location new --category podcast --domain open.spotify.com
uv run rwr-list --location archive --limit 50 --fields id,title,source_url
uv run rwr-list --location later --fields all          # full document objects
```

| flag | default | meaning |
|------|---------|---------|
| `--location` | `new` | `new` (inbox) / `later` / `shortlist` / `archive` / `feed` |
| `--category` | — | server-side category filter (`podcast`, `article`, `video`, …) |
| `--domain` | — | client-side substring filter on `source_url`/`url` (no server domain filter exists) |
| `--updated-after` | — | ISO-8601 `updatedAfter` cutoff |
| `--limit` | `0` | cap total returned (0 = no cap; paginates fully) |
| `--fields` | id,title,author,category,source_url,url,site_name,word_count,created_at | comma-separated fields, or `all` |

Output: a JSON array of documents.

### `rwr-get` — one document's metadata + transcript

```bash
uv run rwr-get 01abc...            # metadata + raw html_content
uv run rwr-get 01abc... --text     # transcript as clean plain text (timestamps stripped)
uv run rwr-get 01abc... --text --keep-timestamps
```

For podcasts, the transcript comes back inside `html_content`; `--text` strips HTML and
`[0:00]`-style timestamps into readable prose.

### `rwr-move` — move a document

```bash
uv run rwr-move 01abc... archive   # e.g. inbox -> archive after archiving its transcript
```

Target location must be one of `new` / `later` / `archive` / `feed`.

### `rwr-update` — modify a document (tags / notes / location)

```bash
rwr-update <id> --tags "python programming" --location later
rwr-update <id> --notes "my note"          # only the flags you pass are sent
```

Note: `--tags` **replaces** the document's tags (it does not merge). Flags use
underscores (`--set_empty_notes`), matching the other tools.

### `rwr-save` — save a URL to Reader

```bash
uv run rwr-save "https://open.spotify.com/episode/abc123"
uv run rwr-save "https://example.com/article" --tags "podcast,to-read" --location new
```

Idempotent-by-url: saving an already-known URL returns the existing doc, no duplicate.
**Not** idempotent on location — re-saving an existing doc resurfaces it to `location=new`
even with no `--location` passed (live-verified 2026-07-09). Does not trigger transcription
for a podcast URL — that's still a manual "Load Transcript" click in Reader itself.

## Classic Readwise tools (`rw-*`)

### `rw-books` — list highlighted sources (classic Readwise)

```bash
uv run rw-books --category podcasts --limit 20
uv run rw-books --category podcasts --fields all
```

| flag | default | meaning |
|------|---------|---------|
| `--category` | — | server-side category filter (`podcasts`, `books`, `articles`, …) |
| `--updated-after` | — | ISO-8601 `updated__gt` cutoff |
| `--limit` | `0` | cap total returned (0 = no cap; paginates fully via DRF `next`) |
| `--fields` | id,title,author,category,source,source_url,highlights_url,num_highlights,updated | comma-separated fields, or `all` |

Every result has `num_highlights >= 1` by construction — a book record only exists in
classic Readwise if it has at least one highlight, so there's no separate "has highlights"
filter to apply. `source_url` is the Snipd share link for Snipd-sourced podcasts;
`highlights_url` is Readwise's own highlight-review page (a different URL, easy to confuse).

### `rw-prompt` — fetch a prompt from the prompts-sync-library

```bash
rw-prompt estimate-quality            # git pull, then print prompts-latest/estimate-quality.md (frontmatter stripped)
rw-prompt add-topic-tags --no_pull    # read the cached copy, no pull
```

Doesn't hit either Readwise API — reads the locally-cloned `promptslibrarysync` repo.

## Rate & tag pipeline (n8n "Rate and tag sources" rebuild)

Three building-block CLIs plus an orchestrator resurrect the old n8n workflow as
owned code. The LLM is reached only through `bun ~/.claude/PAI/TOOLS/Inference.ts`
(`--level fast` = Haiku, the cheapest tier; one flag to swap models later), and
prompts come from the locally-cloned `promptslibrarysync` repo.

### `rwr-rate` — rate a document's reading-ROI tier (S/A/B/C/D)

```bash
rwr-rate --id <doc>                    # fetch + rate a Reader doc
cat article.md | rwr-rate --text_file -
```
Output: `{tier, model, quality}`. Uses the `estimate-quality` prompt.

### `rwr-tag` — topic tags from a fixed vocabulary

```bash
rwr-tag --id <doc>                     # tags chosen ONLY from add-topic-tags' embedded vocabulary (dup-proof)
```
Output: a JSON array of tags.

### `rwr-rate-tag` — the nightly orchestrator

```bash
rwr-rate-tag --dry_run --limit 2       # rate+tag, print the planned PATCH, write nothing
rwr-rate-tag --limit 10                # the scheduled behavior
```

For each `location=new` item, capped by `--limit`: skip if already `_rating`-tagged;
`word_count > 10000` or empty → `PROCESS_MANUAL`; otherwise rate + tag, append
`_rating/<TIER>/claude-haiku`, write a quality-summary markdown into notes, and move
`new → later`. Then it feeds `consume-selection` (`cs-ingest` + `cs-groundtruth`).

**Nightly:** a systemd-user timer (`readwise-rate-tag.timer`, 04:00) runs
`~/.claude/scripts/run-readwise-rate-tag-nightly.sh`, which caps each run at **10 items**
and scrubs `CLAUDECODE`/auth env so the nested `claude` uses subscription billing.

## API notes

- Reader LIST is rate-limited to 20/min, UPDATE to 50/min; the client throttles LIST calls
  and honors `Retry-After` on `429`. Classic-Readwise `/books/` reuses the same LIST throttle.
- The Reader API has **no** server-side domain filter — `--domain` filters client-side.
- Document text is only returned when `withHtmlContent=true`; `rwr-get` always requests it.
- Reader pagination is cursor-based (`pageCursor`/`nextPageCursor`); classic Readwise
  `/books/` uses standard DRF `next`-URL pagination — different shapes, same `_call()` retry
  wrapper (it accepts an absolute URL to follow either).

## License

MIT
