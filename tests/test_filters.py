from datetime import timedelta

import pytest
from conftest import TODAY, TZ

from radar.models import Job, normalize_url
from radar.sources.workday import parse_posted_on

KEEP = [
    "Software Engineer I",
    "Software Engineer 1/2",
    "Software Engineer I/II",
    "Associate Software Engineer",
    "Junior Full Stack Engineer",
    "Backend Engineer New Grad",
    "Solutions Engineer",
    "Forward Deployed Engineer",
    "AI Engineer",
    "Application Developer Analyst",
    "Technical Support Engineer",
    "Software Engineer",
    "SW Engineer",
    "Graduate – Digital – Data & AI and Digital Engineering – Houston",
    "React Native Developer",
]
DROP = [
    "Senior Software Engineer",
    "Sr. Software Engineer",
    "Software Engineer III",
    "Software Engineer II",
    "Staff Engineer",
    "Engineering Manager",
    "Software Engineering Intern",
    "Post-Silicon Validation Engineer",
    "Hardware Data Engineer",
    "Account Executive",
    "Principal Data Engineer",
]


@pytest.mark.parametrize("title", KEEP)
def test_title_keep(filters, title):
    assert filters.title_ok(title), title


@pytest.mark.parametrize("title", DROP)
def test_title_drop(filters, title):
    assert not filters.title_ok(title), title


def job(locations, remote=None, posted_at=None, title="Software Engineer"):
    if remote is None:
        remote = any("remote" in l.lower() for l in locations)
    return Job(uid="x:y:1", source="greenhouse", company="Y", title=title, locations=locations,
               remote=remote, url="https://example.com/1", posted_at=posted_at)


@pytest.mark.parametrize("locs,tag", [
    (["Houston, TX"], "loc-preferred"),
    (["Katy, TX"], "loc-preferred"),
    (["Sugar Land, Texas"], "loc-preferred"),
    (["The Woodlands, TX"], "loc-preferred"),
    (["Spring, Texas, United States of America"], "loc-preferred"),
    (["Remote in USA"], "loc-preferred"),
    (["Remote, United States"], "loc-preferred"),
    (["Remote"], "loc-preferred"),
    (["Remote in Canada", "Remote in USA"], "loc-preferred"),
    (["Austin, TX"], "loc-acceptable"),
    (["US - Austin, TX"], "loc-acceptable"),
    (["Round Rock, TX"], "loc-acceptable"),
    (["Plano, TX"], "loc-acceptable"),
    (["Fort Worth, Texas"], "loc-acceptable"),
    (["Marlborough, MA", "Dallas, TX"], "loc-acceptable"),
    (["Remote in Canada"], None),
    (["Remote - UK"], None),
    (["Remote, Canada", "Remote, Poland"], None),
    (["Marlborough, MA"], None),
    (["Madison, WI"], None),
    (["Allentown, PA"], None),
    (["Bengaluru, Karnataka, India"], None),
])
def test_location(filters, locs, tag):
    assert filters.location_tag(job(locs)) == tag


def test_remote_flag_with_us_location(filters):
    assert filters.location_tag(job(["United States"], remote=True)) == "loc-preferred"
    assert filters.location_tag(job(["Toronto, Canada"], remote=True)) is None
    assert filters.location_tag(job(["New York, NY"], remote=True)) == "loc-preferred"


def test_include_other_us(filters_cfg):
    from radar.filters import Filters
    cfg = {**filters_cfg, "location": {**filters_cfg["location"], "include_other_us": True}}
    assert Filters(cfg).location_tag(job(["Marlborough, MA"])) == "other-us"


def test_age(filters):
    fresh = (TODAY - timedelta(days=30)).isoformat() + "T18:00:00Z"
    stale = (TODAY - timedelta(days=31)).isoformat() + "T18:00:00Z"
    assert filters.age_ok(job(["Houston, TX"], posted_at=fresh), TODAY, TZ)
    assert not filters.age_ok(job(["Houston, TX"], posted_at=stale), TODAY, TZ)
    assert filters.age_ok(job(["Houston, TX"], posted_at=None), TODAY, TZ)


def test_apply_adds_tag(filters):
    j = job(["Houston, TX"])
    assert filters.apply(j, TODAY, TZ) and "loc-preferred" in j.tags


@pytest.mark.parametrize("text,days", [
    ("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 3 Days Ago", 3),
    ("Posted 30+ Days Ago", 31), ("Posted 1 Day Ago", 1),
])
def test_workday_posted_on(text, days):
    assert parse_posted_on(text, TODAY) == TODAY - timedelta(days=days)


def test_workday_posted_on_unknown():
    assert parse_posted_on("", TODAY) is None
    assert parse_posted_on("Posted sometime", TODAY) is None


def test_normalize_url():
    assert normalize_url("https://Jobs.Example.COM/a/b/?utm=1#x") == "https://jobs.example.com/a/b"
    assert normalize_url("https://jobs.example.com/a/b") == "https://jobs.example.com/a/b"
    assert normalize_url("https://jobs.ashbyhq.com/x/123/application") == "https://jobs.ashbyhq.com/x/123"
    assert normalize_url("https://apply.workable.com/x/j/AB12/apply/") == "https://apply.workable.com/x/j/AB12"
