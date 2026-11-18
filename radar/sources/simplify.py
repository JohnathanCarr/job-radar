"""SimplifyJobs New-Grad-Positions dataset (listings.json, not the README table)."""

from __future__ import annotations

from ..models import Job, clean, from_epoch, is_remote_text, slug
from . import request_json

URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"

SPONSORSHIP_TAGS = {
    "U.S. Citizenship is Required": "us-citizen-required",
    "Does Not Offer Sponsorship": "no-sponsorship",
    "Offers Sponsorship": "offers-sponsorship",
}


def parse(records: list[dict], categories: set[str]) -> list[Job]:
    jobs = []
    for r in records:
        if not (r.get("active") and r.get("is_visible")):
            continue
        if r.get("category") not in categories:
            continue
        company = clean(r["company_name"])
        locations = [clean(l) for l in r.get("locations") or [] if clean(l)]
        tags = ["simplify"]
        if r.get("sponsorship") in SPONSORSHIP_TAGS:
            tags.append(SPONSORSHIP_TAGS[r["sponsorship"]])
        jobs.append(Job(
            uid=f"simplify:{slug(company)}:{r['id']}",
            source="simplify",
            company=company,
            title=clean(r["title"]),
            locations=locations,
            remote=any(is_remote_text(l) for l in locations),
            url=r["url"],
            posted_at=from_epoch(r.get("date_posted")),
            company_size=None,
            tags=tags,
            meta={"category": r.get("category"), "degrees": r.get("degrees") or [],
                  "sponsorship": r.get("sponsorship")},
        ))
    return jobs


def fetch(session, categories: set[str]) -> tuple[int, list[Job]]:
    records = request_json(session, "GET", URL)
    return len(records), parse(records, categories)
