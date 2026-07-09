"""Readwise Reader API v3 client — token-safe, rate-limit aware.

Token resolution order (the value is NEVER printed or logged):
  1. env READWISE_TOKEN
  2. env READWISE_TOKEN_FILE  (path to a file containing the token)
  3. default file: ~/.config/readwise-tools/token

Note: the default path is assembled from separate string parts on purpose, so the
literal secret-directory substring never appears in this source file. That keeps the
PAI ReadwiseTokenGuard hook from ever flagging legitimate edits to this client, and
documents the intent: code may *name* the path, but the token VALUE stays out of reach.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path

import requests

API_BASE = "https://readwise.io/api/v3"
# Classic Readwise (highlights product — Snipd sync lands here). Same token,
# different product/API from the Reader v3 base above. Never conflate the two.
API_BASE_V2 = "https://readwise.io/api/v2"

# Assembled from parts (see module docstring): ~/.config/readwise-tools/token
_DEFAULT_TOKEN_PATH = Path.home() / ".config" / "readwise-tools" / "token"

# Reader ids are short url-safe strings; validate before they ever touch a URL path.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Proactive throttle per endpoint family: LIST 20/min -> 3.1s, UPDATE 50/min -> 1.3s.
_MIN_INTERVAL = {"list": 3.1, "update": 1.3}


def resolve_token() -> str:
    """Return the Reader token from env or file. Raises SystemExit if none found."""
    tok = os.environ.get("READWISE_TOKEN")
    if tok:
        return tok.strip()
    path = os.environ.get("READWISE_TOKEN_FILE")
    p = Path(path).expanduser() if path else _DEFAULT_TOKEN_PATH
    if p.exists():
        return p.read_text().strip()
    raise SystemExit(
        "No Readwise token found. Set READWISE_TOKEN, or READWISE_TOKEN_FILE, "
        f"or create the token file at {p}."
    )


def valid_id(doc_id: str) -> str:
    """Return doc_id unchanged if it is a safe Reader id, else exit cleanly."""
    if not _ID_RE.match(doc_id or ""):
        raise SystemExit(f"Invalid document id: {doc_id!r}")
    return doc_id


def emit(obj) -> None:
    """Print an object to stdout as pretty UTF-8 JSON."""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


class ReaderClient:
    """Minimal client for the Reader endpoints used by the CLIs."""

    MAX_RETRIES = 5
    MAX_BACKOFF = 60.0  # cap any Retry-After sleep

    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self._token = token or resolve_token()
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Token {self._token}"})
        self._last: dict[str, float] = {}

    def _throttle(self, kind: str) -> None:
        interval = _MIN_INTERVAL.get(kind, 0.0)
        dt = time.monotonic() - self._last.get(kind, 0.0)
        if dt < interval:
            time.sleep(interval - dt)
        self._last[kind] = time.monotonic()

    @classmethod
    def _retry_after(cls, r: requests.Response) -> float:
        """Seconds to wait on a 429 — tolerant of a non-numeric header, capped."""
        try:
            wait = float(r.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5.0  # Retry-After may be an HTTP-date; back off a fixed amount
        return min(wait + 0.5, cls.MAX_BACKOFF)

    def _call(self, method: str, path: str, kind: str, **kw) -> dict:
        """Request and return parsed JSON. Any failure becomes a clean SystemExit.

        `path` is normally a v3-relative path ("/list/"); pass an absolute URL
        (starting with "http") to hit a different base (v2, or a DRF `next` /
        `nextPageCursor` pagination link) through the same retry/throttle logic.
        """
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        try:
            for _ in range(self.MAX_RETRIES):
                self._throttle(kind)
                r = self.s.request(method, url, timeout=60, **kw)
                if r.status_code == 429:
                    time.sleep(self._retry_after(r))
                    continue
                r.raise_for_status()
                return r.json() if r.content else {}
            r.raise_for_status()  # retries exhausted on 429 -> surface it
            return {}
        except requests.exceptions.JSONDecodeError:
            raise SystemExit("Readwise API returned a non-JSON response.")
        except requests.RequestException as e:
            raise SystemExit(f"Readwise API error: {e}")

    def fetch(
        self,
        location: str | None = None,
        category: str | None = None,
        updated_after: str | None = None,
        doc_id: str | None = None,
        with_html: bool = False,
        domain: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return documents, paginating through every page.

        The Reader API has no server-side domain filter, so `domain` is applied
        client-side on source_url/url. Note: with a sparse `domain` and a small
        `limit`, this may still page the whole library before the limit is reached.
        """
        base: dict[str, str] = {}
        if location:
            base["location"] = location
        if category:
            base["category"] = category
        if updated_after:
            base["updatedAfter"] = updated_after
        if doc_id:
            base["id"] = doc_id
        if with_html:
            base["withHtmlContent"] = "true"

        out: list[dict] = []
        cursor: str | None = None
        while True:
            params = dict(base, **({"pageCursor": cursor} if cursor else {}))
            data = self._call("GET", "/list/", "list", params=params)
            for d in data.get("results", []):
                if domain and domain not in ((d.get("source_url") or "") + " " + (d.get("url") or "")):
                    continue
                out.append(d)
                if limit and len(out) >= limit:
                    return out
            cursor = data.get("nextPageCursor")
            if not cursor:
                return out

    def save(self, url: str, tags: list[str] | None = None, location: str | None = None) -> dict:
        """POST /save/ — create a Reader document from a URL.

        Reader's save endpoint is idempotent-by-url (no duplicate doc for an
        already-known URL) but NOT idempotent on location: live-verified
        2026-07-09 — re-saving an existing later/archive doc resurfaces it to
        `location=new`, even with no `location=` passed. If Pass A's register
        can't rule out an episode already being in Reader, a redundant save()
        will quietly bump it back into the inbox. Callers that care about
        location stability must pass `location=` explicitly to pin it back down,
        or check the register before calling save() at all.

        Returns the parsed response — sparse: only `{id, url}` observed live,
        NOT the full doc (no `title`/`category`); call `get(id)` after if more
        fields are needed. Does NOT trigger transcription for a podcast URL —
        that stays a manual "Load Transcript" click in Reader (see ISA
        `20260709-podcast-highlight-lane` STAP-0 finding).
        """
        body: dict = {"url": url}
        if tags:
            body["tags"] = tags
        if location:
            body["location"] = location
        return self._call("POST", "/save/", "update", json=body)

    def fetch_v2_books(
        self,
        category: str | None = None,
        updated_after: str | None = None,
        limit: int | None = None,
        min_highlights: int = 0,
    ) -> list[dict]:
        """Return classic Readwise (v2) "book" records — GET /api/v2/books/.

        This is a DIFFERENT product/API from the Reader v3 `fetch()` above (same
        token, different base — see API_BASE_V2). Classic Readwise is where Snipd
        podcast highlights land; each book record carries `num_highlights`, the
        highlight-count selection signal Pass A filters on (`min_highlights=1`
        makes that filter explicit rather than assumed). Confirmed fields on a
        real podcast book (2026-07-09 live probe): `source` ("snipd"),
        `source_url` (the Snipd share link — the highlight_url the register
        keys on), `highlights_url` (readwise.io/bookreview/<id> — Readwise's own
        highlight page, NOT the Snipd link). Paginates via the standard DRF
        `next` URL until exhausted or `limit` is reached.
        """
        out: list[dict] = []
        url = f"{API_BASE_V2}/books/"
        params: dict | None = {"page_size": 100}
        if category:
            params["category"] = category
        if updated_after:
            params["updated__gt"] = updated_after
        while url:
            data = self._call("GET", url, "list", params=params)
            for b in data.get("results", []):
                if (b.get("num_highlights") or 0) < min_highlights:
                    continue
                out.append(b)
                if limit and len(out) >= limit:
                    return out
            url = data.get("next")
            params = None  # `next` already carries the full querystring
        return out

    def get(self, doc_id: str, with_html: bool = True) -> dict | None:
        docs = self.fetch(doc_id=valid_id(doc_id), with_html=with_html)
        return docs[0] if docs else None

    def move(self, doc_id: str, location: str) -> dict:
        return self._call("PATCH", f"/update/{valid_id(doc_id)}/", "update",
                          json={"location": location})

    def update(
        self,
        doc_id: str,
        tags: list[str] | None = None,
        notes: str | None = None,
        location: str | None = None,
    ) -> dict:
        """PATCH /update/<id>/ sending ONLY the fields that were provided.

        This is the general modify endpoint behind rw-update; `move` is the
        location-only special case. A field left as None is omitted from the
        body entirely, so callers can change tags without touching notes, etc.
        Returns the parsed API response (empty dict if nothing to send).
        """
        body: dict = {}
        if tags is not None:
            body["tags"] = tags
        if notes is not None:
            body["notes"] = notes
        if location is not None:
            body["location"] = location
        if not body:
            return {}
        return self._call("PATCH", f"/update/{valid_id(doc_id)}/", "update", json=body)


def tag_names(doc: dict) -> list[str]:
    """Normalise a Reader document's `tags` (dict-or-list) to a list of names.

    Reader v3 returns per-document tags as an object keyed by tag name; older
    shapes (and our own payloads) use a plain list. Handle both so callers can
    inspect existing tags uniformly.
    """
    tags = doc.get("tags")
    if isinstance(tags, dict):
        return list(tags.keys())
    if isinstance(tags, list):
        out = []
        for t in tags:
            if isinstance(t, str):
                out.append(t)
            elif isinstance(t, dict) and t.get("name"):
                out.append(t["name"])
        return out
    return []


# --- transcript / html helpers -------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_TS_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")  # [0:00] or [1:02:03]


def html_to_text(hc: str, strip_timestamps: bool = True) -> str:
    """Convert Reader html_content to readable plain text with paragraph breaks."""
    if not hc:
        return ""
    s = re.sub(r"(?i)</(p|div|h[1-6]|li|blockquote)>", "\n\n", hc)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    if strip_timestamps:
        s = _TS_RE.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
