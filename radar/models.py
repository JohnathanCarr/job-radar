"""Job record and normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

SOURCES = ("greenhouse", "lever", "ashby", "workday", "simplify")


@dataclass
class Job:
    uid: str
    source: str
    company: str
    title: str
    locations: list[str]
    remote: bool
    url: str
    posted_at: str | None
    first_seen: str = ""
    company_size: str | None = None
    tags: list[str] = field(default_factory=list)
    # Not part of the triage contract; debugging/provenance only.
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "uid": self.uid,
            "source": self.source,
            "company": self.company,
            "title": self.title,
            "locations": list(self.locations),
            "remote": self.remote,
            "url": self.url,
            "posted_at": self.posted_at,
            "first_seen": self.first_seen,
            "company_size": self.company_size,
            "tags": sorted(set(self.tags)),
            "meta": dict(sorted(self.meta.items())),
        }
        return dict(sorted(d.items()))

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_url(url: str) -> str:
    """Dedupe key: lowercase scheme/host, drop query/fragment, trailing slash and /apply."""
    parts = urlsplit(url.strip())
    path = re.sub(r"/(apply|application)$", "", parts.path.rstrip("/"), flags=re.I)
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, "", ""))


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_epoch(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    return iso_utc(datetime.fromtimestamp(float(seconds), tz=timezone.utc))


def from_iso(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return iso_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def is_remote_text(text: str) -> bool:
    return "remote" in text.lower()
