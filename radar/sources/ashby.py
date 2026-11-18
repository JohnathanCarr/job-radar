"""Ashby public job board API."""

from __future__ import annotations

from ..models import Job, clean, from_iso, is_remote_text, slug
from . import request_json

URL = "https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=false"


def parse(data: dict, entry: dict) -> list[Job]:
    jobs = []
    fetched = data.get("jobs", [])
    for j in fetched:
        if j.get("isListed") is False:
            continue
        locations = [clean(j.get("location"))] if clean(j.get("location")) else []
        for sec in j.get("secondaryLocations") or []:
            l = clean(sec.get("location"))
            if l and l not in locations:
                locations.append(l)
        jobs.append(Job(
            uid=f"ashby:{slug(entry['slug'])}:{j['id']}",
            source="ashby",
            company=entry["name"],
            title=clean(j["title"]),
            locations=locations,
            remote=bool(j.get("isRemote")) or any(map(is_remote_text, locations)),
            url=j["jobUrl"],
            posted_at=from_iso(j.get("publishedAt")),
            company_size=entry.get("size"),
            tags=["watchlist"],
            meta={"workplace_type": j.get("workplaceType")},
        ))
    return jobs


def fetch(session, entry: dict, title_ok=None) -> tuple[int, list[Job]]:
    data = request_json(session, "GET", URL.format(company=entry["slug"]))
    return len(data.get("jobs", [])), parse(data, entry)
