"""Source fetchers. Each ATS module exposes `parse(...)` (pure, fixture-tested) and `fetch(...)`."""

from __future__ import annotations

import time

import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-radar/0.1; daily poll of public job boards)"
# Workday answers HTTP 429 to non-browser User-Agents, so Workday requests use a browser UA
# (owner-approved 2026-11-18). Other sources keep the descriptive UA above.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 30


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def request_json(session: requests.Session, method: str, url: str, retries: int = 2, **kw):
    """HTTP JSON request with a short retry on connection errors and 5xx/429."""
    for attempt in range(retries + 1):
        try:
            r = session.request(method, url, timeout=TIMEOUT, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= retries:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")
