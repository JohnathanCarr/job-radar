"""Suggest watchlist entries from the Simplify dataset.

python -m radar.suggest [--days 60] [--min 1]

Lists companies with at least --min Texas or remote-US software roles posted in the last --days,
whose posting URLs are on Greenhouse, Lever, Ashby or Workday and that aren't already in
config/watchlist.yaml. Prints watchlist.yaml stubs (size/city/why left for you to fill in).
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import yaml

from .filters import is_foreign, is_us, normalize_location
from .main import ROOT
from .models import is_remote_text
from .sources import make_session, request_json, simplify

_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_WD_HOST = re.compile(r"^([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com$")


def detect_ats(url: str) -> dict | None:
    """Map a posting URL to a watchlist key: {ats, slug} or {ats, tenant, wd, site}."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    segs = [s for s in parts.path.split("/") if s]
    if host.endswith("greenhouse.io"):
        token = parse_qs(parts.query).get("for", [None])[0]
        if not token and segs and segs[0] not in ("embed", "job_app"):
            token = segs[0]
        return {"ats": "greenhouse", "slug": token} if token else None
    if host == "jobs.lever.co" and segs:
        return {"ats": "lever", "slug": segs[0]}
    if host == "jobs.ashbyhq.com" and segs:
        return {"ats": "ashby", "slug": segs[0]}
    if m := _WD_HOST.match(host):
        site = next((s for s in segs if not _LOCALE.match(s)), None)
        if site:
            return {"ats": "workday", "tenant": m.group(1), "wd": int(m.group(2)), "site": site}
    return None


def texas_or_remote_us(locations: list[str]) -> bool:
    for raw in locations:
        loc = normalize_location(raw)
        if is_remote_text(loc) and not is_foreign(loc):
            return True
        if re.search(r",\s*TX\b|\bTexas\b", loc):
            return True
    return False


def watch_key(e: dict) -> tuple:
    if e["ats"] == "workday":
        return ("workday", str(e["tenant"]).lower())
    return (e["ats"], str(e["slug"]).lower())


def suggest(records: list[dict], categories: set[str], watchlist: list[dict], now: datetime,
            days: int = 60, minimum: int = 1) -> list[dict]:
    """Return stubs sorted by role count desc, then name. Pure; tested with fixtures."""
    cutoff = (now - timedelta(days=days)).timestamp()
    watched = {watch_key(e) for e in watchlist}
    found: dict[tuple, dict] = {}
    counts: dict[tuple, int] = defaultdict(int)
    examples: dict[tuple, str] = {}
    sites: dict[tuple, set] = defaultdict(set)
    for r in records:
        if not (r.get("active") and r.get("is_visible")) or r.get("category") not in categories:
            continue
        if (r.get("date_posted") or 0) < cutoff or not texas_or_remote_us(r.get("locations") or []):
            continue
        ats = detect_ats(r.get("url") or "")
        if not ats:
            continue
        key = watch_key(ats)
        if key in watched:
            continue
        found.setdefault(key, {"name": r["company_name"].strip(), **ats})
        if ats["ats"] == "workday":
            sites[key].add(ats["site"])
        counts[key] += 1
        examples.setdefault(key, r["title"].strip())
    stubs = []
    for key, stub in found.items():
        if counts[key] < minimum:
            continue
        if key in sites:
            s = sorted(sites[key])
            stub["site"] = s[0] if len(s) == 1 else s
        stub.update({"size": None, "city": None,
                     "why": f"Simplify: {counts[key]} TX/remote-US software role(s) in {days}d, e.g. {examples[key]!r}"})
        stub["_count"] = counts[key]
        stubs.append(stub)
    stubs.sort(key=lambda s: (-s["_count"], s["name"].lower()))
    for s in stubs:
        del s["_count"]
    return stubs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--min", type=int, default=1, dest="minimum")
    args = ap.parse_args(argv)

    filters_cfg = yaml.safe_load((ROOT / "config" / "filters.yaml").read_text())
    watchlist = yaml.safe_load((ROOT / "config" / "watchlist.yaml").read_text()) or []
    records = request_json(make_session(), "GET", simplify.URL)
    stubs = suggest(records, set(filters_cfg["simplify"]["categories"]), watchlist,
                    datetime.now(timezone.utc), args.days, args.minimum)
    print(f"# {len(stubs)} suggestions. Verify each endpoint before adding to config/watchlist.yaml.")
    print(yaml.safe_dump(stubs, sort_keys=False, allow_unicode=True, width=200), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
