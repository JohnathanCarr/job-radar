"""Workday CXS job search (unofficial JSON endpoint behind myworkdayjobs.com)."""

from __future__ import annotations

import re
import time
from datetime import date, datetime, time as dtime, timedelta

from ..models import Job, clean, is_remote_text, iso_utc, slug
from . import BROWSER_USER_AGENT, request_json

PAGE = 20
CAP = 200              # max postings read per company (across all searches)
DELAY = 1.0            # seconds between requests to the same tenant
DEFAULT_SEARCHES = ("software", "developer", "engineer")
HEADERS = {"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json", "Accept-Language": "en-US"}

_REQ_ID = re.compile(r"^[A-Za-z]{0,6}[-_]?\d{4,}[A-Za-z0-9_-]*$")
_MULTI = re.compile(r"^\d+\s+Locations?$", re.I)


def host(entry: dict) -> str:
    return f"https://{entry['tenant']}.wd{entry['wd']}.myworkdayjobs.com"


def sites(entry: dict) -> list[str]:
    s = entry["site"]
    return [s] if isinstance(s, str) else list(s)


def parse_posted_on(text: str | None, today: date) -> date | None:
    """'Posted Today'=0, 'Posted Yesterday'=1, 'Posted N Days Ago'=N, '30+ Days Ago'=31."""
    if not text:
        return None
    t = text.lower()
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    elif m := re.search(r"(\d+)\+", t):
        days = int(m.group(1)) + 1
    elif m := re.search(r"(\d+)\s+day", t):
        days = int(m.group(1))
    else:
        return None
    return today - timedelta(days=days)


def req_id(posting: dict) -> str | None:
    for b in posting.get("bulletFields") or []:
        if isinstance(b, str) and _REQ_ID.match(b.strip()):
            return b.strip()
    return None


def parse_posting(p: dict, entry: dict, site: str, today: date, tz, locations=None) -> Job:
    rid = req_id(p)
    key = rid or p["externalPath"]
    loc_text = clean(p.get("locationsText"))
    if locations is None:
        locations = [loc_text] if loc_text and not _MULTI.match(loc_text) else []
    posted = parse_posted_on(p.get("postedOn"), today)
    return Job(
        uid=f"workday:{slug(entry['name'])}:{key}",
        source="workday",
        company=entry["name"],
        title=clean(p["title"]),
        locations=locations,
        remote=any(map(is_remote_text, locations + [loc_text])),
        url=f"{host(entry)}/{site}{p['externalPath']}",
        # Midday Chicago time on the derived date keeps the UTC date the same.
        posted_at=iso_utc(datetime.combine(posted, dtime(12), tz)) if posted else None,
        company_size=entry.get("size"),
        tags=["watchlist"],
        meta={"posted_at_approx": True, "req_id": rid, "site": site},
    )


def parse(data: dict, entry: dict, site: str, today: date, tz) -> list[Job]:
    return [parse_posting(p, entry, site, today, tz) for p in data.get("jobPostings", [])]


def detail_locations(detail: dict) -> list[str]:
    info = detail.get("jobPostingInfo") or {}
    locs = [info.get("location"), *(info.get("additionalLocations") or [])]
    return [clean(l) for l in locs if clean(l)]


def fetch(session, entry: dict, title_ok, today: date, tz) -> tuple[int, list[Job]]:
    """Read up to CAP postings per company; resolve 'N Locations' only for title matches."""
    base = host(entry)
    tenant = entry["tenant"]
    found: dict[str, Job] = {}
    read = 0
    last = 0.0

    def call(method, url, **kw):
        nonlocal last
        wait = DELAY - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        try:
            return request_json(session, method, url, headers=HEADERS, **kw)
        finally:
            last = time.monotonic()

    for site in sites(entry):
        api = f"{base}/wday/cxs/{tenant}/{site}"
        for search in entry.get("search") or DEFAULT_SEARCHES:
            offset, total = 0, None
            while read < CAP:
                body = {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": search}
                data = call("POST", f"{api}/jobs", json=body)
                postings = data.get("jobPostings") or []
                if total is None:
                    total = data.get("total") or 0  # only reliable on the first page
                if not postings:
                    break
                read += len(postings)
                for p in postings:
                    job = parse_posting(p, entry, site, today, tz)
                    if job.uid in found:
                        continue
                    if not job.locations and _MULTI.match(clean(p.get("locationsText"))) and title_ok(job.title):
                        try:
                            job = parse_posting(p, entry, site, today, tz,
                                                locations=detail_locations(call("GET", f"{api}{p['externalPath']}")))
                        except Exception as e:  # keep the posting; triage can open it
                            job.meta["detail_error"] = str(e)[:200]
                    found[job.uid] = job
                offset += len(postings)
                if offset >= total:
                    break
    return read, list(found.values())
