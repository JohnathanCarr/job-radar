"""Entry point: python -m radar.main [--bootstrap]"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import state
from .filters import LOC_RANK, Filters
from .models import Job, iso_utc, normalize_url
from .sources import ashby, greenhouse, lever, make_session, simplify, workday

TZ = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_NEW_DAYS = 7
ATS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}


def feed_key(entry: dict) -> str:
    if entry["ats"] == "workday":
        return f"workday:{entry['tenant']}"
    return f"{entry['ats']}:{entry['slug']}"


def load_config(config_dir: Path) -> tuple[dict, list[dict]]:
    filters_cfg = yaml.safe_load((config_dir / "filters.yaml").read_text())
    watchlist = yaml.safe_load((config_dir / "watchlist.yaml").read_text()) or []
    for e in watchlist:
        if e.get("ats") not in ATS:
            raise ValueError(f"watchlist entry {e.get('name')!r}: unsupported ats {e.get('ats')!r}")
    return filters_cfg, watchlist


def run_feed(key, entry, filters, filters_cfg, today, session):
    """Fetch one feed. Never raises; returns (key, fetched, jobs, error)."""
    try:
        if entry is None:
            cats = set(filters_cfg["simplify"]["categories"])
            fetched, jobs = simplify.fetch(session, cats)
        elif entry["ats"] == "workday":
            fetched, jobs = workday.fetch(session, entry, filters.title_ok, today, TZ)
        else:
            fetched, jobs = ATS[entry["ats"]].fetch(session, entry)
        for j in jobs:
            j.meta["feed"] = key
        return key, fetched, jobs, None
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return key, 0, [], f"{type(e).__name__}: {e}"[:500]


def best_loc_tag(tags) -> str | None:
    loc = [t for t in tags if t in LOC_RANK]
    return min(loc, key=LOC_RANK.__getitem__) if loc else None


def dedupe(jobs: list[Job]) -> list[Job]:
    """Dedupe by uid, then across sources by normalized URL (ATS record wins, tags merge)."""
    by_uid: dict[str, Job] = {}
    for j in sorted(jobs, key=lambda j: j.uid):
        by_uid.setdefault(j.uid, j)
    groups: dict[str, list[Job]] = {}
    for j in by_uid.values():
        groups.setdefault(normalize_url(j.url), []).append(j)
    out = []
    for group in groups.values():
        group.sort(key=lambda j: (j.source == "simplify", j.uid))
        keep = group[0]
        if len(group) > 1:
            tags = set().union(*(g.tags for g in group))
            loc = best_loc_tag(tags)
            keep.tags = sorted({t for t in tags if t not in LOC_RANK} | ({loc} if loc else set()))
            keep.meta["alt_uids"] = sorted(g.uid for g in group[1:])
        out.append(keep)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", action="store_true",
                    help=f"fill seen/jobs; new.json gets only jobs posted in the last {BOOTSTRAP_NEW_DAYS} days")
    ap.add_argument("--config", type=Path, default=ROOT / "config")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--today", type=date.fromisoformat, help="override run date (America/Chicago)")
    ap.add_argument("--only", help="only run feeds whose key contains this text (debugging)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    run_at = iso_utc(datetime.now(timezone.utc))
    today = args.today or datetime.now(TZ).date()
    filters_cfg, watchlist = load_config(args.config)
    filters = Filters(filters_cfg)

    if not (args.data / "seen.json").exists():
        args.bootstrap = True  # first run ever: never flood triage
    seen = state.load_seen(args.data / "seen.json")
    prev_jobs = {u: Job.from_dict(d) for u, d in state.load_json(args.data / "jobs.json", {}).get("jobs", {}).items()}

    feeds: list[tuple[str, dict | None]] = [("simplify", None)] + [(feed_key(e), e) for e in watchlist]
    if args.only:
        feeds = [f for f in feeds if args.only in f[0]]

    session = make_session()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda f: run_feed(f[0], f[1], filters, filters_cfg, today, session), feeds))

    log: dict[str, dict] = {}
    kept: list[Job] = []
    for (key, entry), (_, fetched, jobs, error) in zip(feeds, results):
        k = [j for j in jobs if filters.apply(j, today, TZ)]
        if error:
            # Carry the feed's previous matches forward so jobs.json doesn't flap on outages.
            k = [j for j in prev_jobs.values() if j.meta.get("feed") == key and filters.age_ok(j, today, TZ)]
        kept.extend(k)
        log[key] = {
            "source": "simplify" if entry is None else entry["ats"],
            "company": None if entry is None else entry["name"],
            "fetched": fetched,
            "kept": 0 if error else len(k),
            "new": 0,
            "error": error,
        }

    jobs = dedupe(kept)

    # Workday dates are derived from relative text; keep the earliest one we've recorded.
    for j in jobs:
        prev = prev_jobs.get(j.uid)
        if prev and prev.posted_at and j.meta.get("posted_at_approx") and (not j.posted_at or prev.posted_at < j.posted_at):
            j.posted_at = prev.posted_at
    jobs = [j for j in jobs if filters.age_ok(j, today, TZ)]

    new = state.assign_first_seen(jobs, seen, today.isoformat())
    for j in new:
        log[j.meta["feed"]]["new"] += 1
    reported = new
    if args.bootstrap:
        cutoff = today - timedelta(days=BOOTSTRAP_NEW_DAYS)
        reported = [j for j in new if j.posted_at and
                    datetime.fromisoformat(j.posted_at.replace("Z", "+00:00")).astimezone(TZ).date() >= cutoff]

    seen = state.prune_seen(seen, today, keep={j.uid for j in jobs})
    jobs_sorted = state.sort_for_jobs(jobs)
    new_sorted = state.sort_for_new(reported)

    errored = sorted(k for k, v in log.items() if v["error"])
    failed = len(errored) * 2 > len(feeds)

    state.write_json(args.data / "jobs.json", {
        "run_at": run_at, "count": len(jobs_sorted), "jobs": {j.uid: j.to_dict() for j in jobs_sorted}})
    state.write_json(args.data / "new.json", {
        "run_at": run_at, "count": len(new_sorted), "jobs": [j.to_dict() for j in new_sorted]})
    state.write_json(args.data / "seen.json", seen)
    state.write_json(args.data / "run_log.json", {
        "run_at": run_at,
        "run_date": today.isoformat(),
        "bootstrap": args.bootstrap,
        "runtime_seconds": round(time.monotonic() - t0, 1),
        "totals": {"feeds": len(feeds), "errored": len(errored), "matching": len(jobs_sorted),
                   "new": len(new), "reported_new": len(new_sorted)},
        "errored_feeds": errored,
        "failed": failed,
        "feeds": dict(sorted(log.items())),
    })

    print(f"radar: {len(feeds)} feeds, {len(errored)} errored, {len(jobs_sorted)} matching, "
          f"{len(new)} new, {len(new_sorted)} in new.json")
    for k in errored:
        print(f"  error {k}: {log[k]['error']}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
