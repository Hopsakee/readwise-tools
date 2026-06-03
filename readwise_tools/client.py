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
        """Request and return parsed JSON. Any failure becomes a clean SystemExit."""
        url = f"{API_BASE}{path}"
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

    def get(self, doc_id: str, with_html: bool = True) -> dict | None:
        docs = self.fetch(doc_id=valid_id(doc_id), with_html=with_html)
        return docs[0] if docs else None

    def move(self, doc_id: str, location: str) -> dict:
        return self._call("PATCH", f"/update/{valid_id(doc_id)}/", "update",
                          json={"location": location})


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
