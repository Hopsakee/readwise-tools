# readwise-tools

Small, composable CLI tools over the [Readwise Reader API v3](https://readwise.io/reader_api):
list documents, fetch a document's text + metadata, and move documents between locations.

Built to feed a personal Library archive pipeline (Spotify-podcast transcripts → Library →
wiki/recall), but each tool is a standalone, pipe-friendly CLI that emits JSON to stdout.

## Install

```bash
uv sync            # create the venv and install the three console scripts
```

Run via `uv run`:

```bash
uv run rw-list --location new
uv run rw-get <document_id> --text
uv run rw-move <document_id> archive
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

## Tools

### `rw-list` — list documents in a location

```bash
uv run rw-list --location new
uv run rw-list --location new --category podcast --domain open.spotify.com
uv run rw-list --location archive --limit 50 --fields id,title,source_url
uv run rw-list --location later --fields all          # full document objects
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

### `rw-get` — one document's metadata + transcript

```bash
uv run rw-get 01abc...            # metadata + raw html_content
uv run rw-get 01abc... --text     # transcript as clean plain text (timestamps stripped)
uv run rw-get 01abc... --text --keep-timestamps
```

For podcasts, the transcript comes back inside `html_content`; `--text` strips HTML and
`[0:00]`-style timestamps into readable prose.

### `rw-move` — move a document

```bash
uv run rw-move 01abc... archive   # e.g. inbox -> archive after archiving its transcript
```

Target location must be one of `new` / `later` / `archive` / `feed`.

### `rw-update` — modify a document (tags / notes / location)

```bash
rw-update <id> --tags "python programming" --location later
rw-update <id> --notes "my note"          # only the flags you pass are sent
```

Note: `--tags` **replaces** the document's tags (it does not merge). Flags use
underscores (`--set_empty_notes`), matching the other tools.

## Rate & tag pipeline (n8n "Rate and tag sources" rebuild)

Three building-block CLIs plus an orchestrator resurrect the old n8n workflow as
owned code. The LLM is reached only through `bun ~/.claude/PAI/TOOLS/Inference.ts`
(`--level fast` = Haiku, the cheapest tier; one flag to swap models later), and
prompts come from the locally-cloned `promptslibrarysync` repo.

### `rw-prompt` — fetch a prompt from the prompts-sync-library

```bash
rw-prompt estimate-quality            # git pull, then print prompts-latest/estimate-quality.md (frontmatter stripped)
rw-prompt add-topic-tags --no_pull    # read the cached copy, no pull
```

### `rw-rate` — rate a document's reading-ROI tier (S/A/B/C/D)

```bash
rw-rate --id <doc>                    # fetch + rate a Reader doc
cat article.md | rw-rate --text_file -
```
Output: `{tier, model, quality}`. Uses the `estimate-quality` prompt.

### `rw-tag` — topic tags from a fixed vocabulary

```bash
rw-tag --id <doc>                     # tags chosen ONLY from add-topic-tags' embedded vocabulary (dup-proof)
```
Output: a JSON array of tags.

### `rw-rate-tag` — the nightly orchestrator

```bash
rw-rate-tag --dry_run --limit 2       # rate+tag, print the planned PATCH, write nothing
rw-rate-tag --limit 10                # the scheduled behavior
```

For each `location=new` item, capped by `--limit`: skip if already `_rating`-tagged;
`word_count > 10000` or empty → `PROCESS_MANUAL`; otherwise rate + tag, append
`_rating/<TIER>/claude-haiku`, write a quality-summary markdown into notes, and move
`new → later`. Then it feeds `consume-selection` (`cs-ingest` + `cs-groundtruth`).

**Nightly:** a systemd-user timer (`readwise-rate-tag.timer`, 04:00) runs
`~/.claude/scripts/run-readwise-rate-tag-nightly.sh`, which caps each run at **10 items**
and scrubs `CLAUDECODE`/auth env so the nested `claude` uses subscription billing.

## API notes

- LIST is rate-limited to 20/min, UPDATE to 50/min; the client throttles LIST calls and
  honors `Retry-After` on `429`.
- The Reader API has **no** server-side domain filter — `--domain` filters client-side.
- Document text is only returned when `withHtmlContent=true`; `rw-get` always requests it.

## License

MIT
