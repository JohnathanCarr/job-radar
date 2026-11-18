"""Lever Postings API."""

from __future__ import annotations

from ..models import Job, clean, from_epoch, is_remote_text, slug
from . import request_json

URL = "https://api.lever.co/v0/postings/{company}?mode=json"


def parse(data: list[dict], entry: dict) -> list[Job]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locations = [clean(l) for l in (cats.get("allLocations") or []) if clean(l)]
        primary = clean(cats.get("location"))
        if primary and primary not in locations:
            locations.insert(0, primary)
        remote = (j.get("workplaceType") or "").lower() == "remote" or any(map(is_remote_text, locations))
        created = j.get("createdAt")
        jobs.append(Job(
            uid=f"lever:{slug(entry['slug'])}:{j['id']}",
            source="lever",
            company=entry["name"],
            title=clean(j["text"]),
            locations=locations,
            remote=remote,
            url=j["hostedUrl"],
            posted_at=from_epoch(created / 1000) if created else None,
            company_size=entry.get("size"),
            tags=["watchlist"],
            meta={"country": j.get("country"), "workplace_type": j.get("workplaceType")},
        ))
    return jobs


def fetch(session, entry: dict, title_ok=None) -> tuple[int, list[Job]]:
    data = request_json(session, "GET", URL.format(company=entry["slug"]))
    jobs = parse(data, entry)
    return len(jobs), jobs
