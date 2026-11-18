"""End-to-end runs of radar.main with fetchers stubbed from fixtures."""

import json
import shutil
from datetime import date, datetime, time, timedelta, timezone

import pytest
import yaml
from conftest import FIXTURES, ROOT, TZ, load_fixture

from radar import main as radar_main
from radar.models import Job
from radar.sources import greenhouse, simplify

TODAY = date(2026, 11, 18)

WATCHLIST = [
    {"name": "Example Co", "ats": "greenhouse", "slug": "exampleco", "size": "M", "city": "Houston", "why": "test"},
    {"name": "Broken Co", "ats": "lever", "slug": "broken", "size": "S", "city": "Austin", "why": "test"},
]


def gh_payload():
    def j(id_, title, loc, published, url=None):
        return {"id": id_, "title": title, "location": {"name": loc}, "first_published": published,
                "updated_at": published, "absolute_url": url or f"https://job-boards.greenhouse.io/exampleco/jobs/{id_}"}
    recent = (TODAY - timedelta(days=2)).isoformat() + "T15:00:00Z"
    older = (TODAY - timedelta(days=20)).isoformat() + "T15:00:00Z"
    stale = (TODAY - timedelta(days=60)).isoformat() + "T15:00:00Z"
    return {"jobs": [
        j(1, "Software Engineer I", "Houston, TX", recent, url="https://careers.example.com/jobs/1?gh_jid=1"),
        j(2, "Senior Software Engineer", "Houston, TX", recent),
        j(3, "Backend Engineer", "Austin, TX", older),
        j(4, "Software Engineer", "Houston, TX", stale),
        j(5, "Data Engineer", "Remote in Canada", recent),
    ]}


def simplify_records():
    base = load_fixture("simplify_listings.json")[0]
    posted = int(datetime.combine(TODAY - timedelta(days=1), time(18), timezone.utc).timestamp())
    return [
        # Same posting as greenhouse job 1 (URL differs only by query string) -> merged
        dict(base, id="s-dup", company_name="Example Co", title="Software Engineer I", locations=["Houston, TX"],
             url="https://careers.example.com/jobs/1/", date_posted=posted,
             sponsorship="U.S. Citizenship is Required"),
        dict(base, id="s-2", company_name="Other Co", title="Associate Software Engineer",
             locations=["Remote in USA"], url="https://other.example.com/2", date_posted=posted),
    ]


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copy(ROOT / "config" / "filters.yaml", cfg / "filters.yaml")
    (cfg / "watchlist.yaml").write_text(yaml.safe_dump(WATCHLIST))
    data = tmp_path / "data"

    monkeypatch.setattr(simplify, "fetch",
                        lambda session, cats: (2, simplify.parse(simplify_records(), cats)))
    monkeypatch.setattr(greenhouse, "fetch",
                        lambda session, entry: (5, greenhouse.parse(gh_payload(), entry)))

    def broken(session, entry):
        raise RuntimeError("HTTP 404")
    monkeypatch.setitem(radar_main.ATS, "lever", type("M", (), {"fetch": staticmethod(broken)}))

    def run(*extra, today=TODAY):
        rc = radar_main.main(["--config", str(cfg), "--data", str(data), "--today", today.isoformat(), *extra])
        out = {n: json.loads((data / f"{n}.json").read_text()) for n in ("jobs", "new", "seen", "run_log")}
        return rc, out
    return run


def test_missing_seen_auto_bootstraps(env):
    rc, out = env()
    assert out["run_log"]["bootstrap"] is True
    assert "greenhouse:exampleco:3" not in [j["uid"] for j in out["new"]["jobs"]]


def test_first_run_then_zero_new(env, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "seen.json").write_text("{}")
    rc, out = env()
    assert rc == 0
    new = out["new"]
    assert set(new) == {"run_at", "count", "jobs"}
    uids = [j["uid"] for j in new["jobs"]]
    # preferred (Remote US posted yesterday, Houston 2 days ago) by posted_at desc, then acceptable (Austin)
    assert uids == ["simplify:other-co:s-2", "greenhouse:exampleco:1", "greenhouse:exampleco:3"]
    assert new["count"] == 3

    merged = new["jobs"][1]
    assert merged["source"] == "greenhouse"
    assert merged["tags"] == ["loc-preferred", "simplify", "us-citizen-required", "watchlist"]
    assert merged["meta"]["alt_uids"] == ["simplify:example-co:s-dup"]
    assert merged["first_seen"] == TODAY.isoformat()
    for key in ("uid", "source", "company", "title", "locations", "remote", "url", "posted_at",
                "first_seen", "company_size", "tags"):
        assert key in merged

    assert list(out["jobs"]["jobs"]) == uids  # same first_seen, so posted_at desc
    assert out["seen"] == {u: TODAY.isoformat() for u in sorted(uids)}

    log = out["run_log"]
    assert log["feeds"]["lever:broken"]["error"] == "RuntimeError: HTTP 404"
    assert log["feeds"]["greenhouse:exampleco"] == {
        "source": "greenhouse", "company": "Example Co", "fetched": 5, "kept": 2, "new": 2, "error": None}
    assert log["failed"] is False

    # Second run, same input, next day: nothing new, first_seen preserved.
    rc, out2 = env(today=TODAY + timedelta(days=1))
    assert out2["new"]["count"] == 0 and out2["new"]["jobs"] == []
    assert all(j["first_seen"] == TODAY.isoformat() for j in out2["jobs"]["jobs"].values())


def test_bootstrap_limits_new(env):
    rc, out = env("--bootstrap")
    # job 3 was posted 20 days ago: in seen/jobs, but not reported in new.json
    assert [j["uid"] for j in out["new"]["jobs"]] == ["simplify:other-co:s-2", "greenhouse:exampleco:1"]
    assert "greenhouse:exampleco:3" in out["seen"] and "greenhouse:exampleco:3" in out["jobs"]["jobs"]


def test_majority_errors_fail(env, monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "seen.json").write_text("{}")

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(simplify, "fetch", boom)
    rc, out = env()
    assert rc == 1 and out["run_log"]["failed"] is True
    assert out["new"]["count"] == 2  # greenhouse still reported and written


def test_output_is_deterministic(env, tmp_path):
    env()
    first = (tmp_path / "data" / "seen.json").read_text()
    env()
    assert (tmp_path / "data" / "seen.json").read_text() == first


def test_prune_keeps_live(tmp_path):
    from radar.state import prune_seen
    seen = {"old:gone": "2026-01-01", "old:live": "2026-01-01", "recent": "2026-11-01"}
    assert prune_seen(seen, TODAY, keep={"old:live"}) == {"old:live": "2026-01-01", "recent": "2026-11-01"}
