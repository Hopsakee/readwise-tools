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

## API notes

- LIST is rate-limited to 20/min, UPDATE to 50/min; the client throttles LIST calls and
  honors `Retry-After` on `429`.
- The Reader API has **no** server-side domain filter — `--domain` filters client-side.
- Document text is only returned when `withHtmlContent=true`; `rw-get` always requests it.

## License

MIT
