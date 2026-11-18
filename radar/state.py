"""seen.json load/save, new-job diff, pruning, and deterministic JSON output."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .filters import LOC_RANK
from .models import Job

PRUNE_DAYS = 120


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def load_seen(path: Path) -> dict[str, str]:
    return dict(load_json(path, {}))


def assign_first_seen(jobs: list[Job], seen: dict[str, str], today: str) -> list[Job]:
    """Set first_seen on every job, add unseen uids to `seen`, return the new jobs.

    A job merged across sources also counts as seen if any of its alternate uids
    (meta["alt_uids"]) was seen before, so a Simplify->ATS merge isn't reported twice.
    """
    new: list[Job] = []
    for job in jobs:
        candidates = [job.uid, *job.meta.get("alt_uids", [])]
        prior = sorted(seen[u] for u in candidates if u in seen)
        if prior:
            job.first_seen = prior[0]
            seen.setdefault(job.uid, prior[0])
        else:
            job.first_seen = today
            seen[job.uid] = today
            new.append(job)
    return new


def prune_seen(seen: dict[str, str], today: date, keep: set[str]) -> dict[str, str]:
    """Drop entries older than PRUNE_DAYS unless the uid is still live (avoids re-reporting)."""
    cutoff = (today - timedelta(days=PRUNE_DAYS)).isoformat()
    return {u: d for u, d in sorted(seen.items()) if d >= cutoff or u in keep}


def _sort(jobs: list[Job], primary) -> list[Job]:
    """Stable multi-key sort: primary key, then posted_at desc (undated last), then uid."""
    out = sorted(jobs, key=lambda j: j.uid)
    out.sort(key=lambda j: j.posted_at or "", reverse=True)
    out.sort(key=lambda j: j.posted_at is None)
    out.sort(key=primary)
    return out


def sort_for_jobs(jobs: list[Job]) -> list[Job]:
    # first_seen desc: sort ascending on a key that inverts the date order.
    return _sort(jobs, lambda j: tuple(-ord(c) for c in j.first_seen))


def loc_rank(job: Job) -> int:
    return min((LOC_RANK[t] for t in job.tags if t in LOC_RANK), default=len(LOC_RANK))


def sort_for_new(jobs: list[Job]) -> list[Job]:
    return _sort(jobs, loc_rank)
