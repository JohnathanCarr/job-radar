"""Greenhouse Job Board API."""

from __future__ import annotations

import re

from ..models import Job, clean, from_iso, is_remote_text, slug
from . import request_json

# content=true is omitted: first_published/updated_at are present without it, and
# descriptions make large boards (SpaceX ~2.8k jobs) many MB per run.
URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def parse(data: dict, entry: dict) -> list[Job]:
    company = entry["name"]
    jobs = []
    for j in data.get("jobs", []):
        loc = clean((j.get("location") or {}).get("name"))
        locations = [p for p in (s.strip() for s in re.split(r"[;|]", loc)) if p] if loc else []
        if j.get("first_published"):
            posted, field = from_iso(j["first_published"]), "first_published"
        else:
            posted, field = from_iso(j.get("updated_at")), "updated_at"
        jobs.append(Job(
            uid=f"greenhouse:{slug(entry['slug'])}:{j['id']}",
            source="greenhouse",
            company=company,
            title=clean(j["title"]),
            locations=locations,
            remote=is_remote_text(loc),
            url=j["absolute_url"],
            posted_at=posted,
            company_size=entry.get("size"),
            tags=["watchlist"],
            meta={"posted_at_field": field},
        ))
    return jobs


def fetch(session, entry: dict, title_ok=None) -> tuple[int, list[Job]]:
    data = request_json(session, "GET", URL.format(token=entry["slug"]))
    jobs = parse(data, entry)
    return len(jobs), jobs
