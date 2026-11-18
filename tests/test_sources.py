from conftest import TODAY, TZ, load_fixture

from radar.sources import ashby, greenhouse, lever, simplify, workday

GH = {"name": "GitLab", "ats": "greenhouse", "slug": "gitlab", "size": "M"}
LV = {"name": "Palantir", "ats": "lever", "slug": "palantir", "size": "L"}
AB = {"name": "Ramp", "ats": "ashby", "slug": "ramp", "size": "M"}
WD = {"name": "Chevron", "ats": "workday", "tenant": "chevron", "wd": 5, "site": ["University", "jobs"], "size": "L"}

CATS = {"Software", "AI/ML/Data", "Software Engineering", "Data Science, AI & Machine Learning"}


def test_simplify_parse():
    jobs = simplify.parse(load_fixture("simplify_listings.json"), CATS)
    # inactive and Hardware records are dropped
    assert [j.title for j in jobs] == ["Software Engineer", "Junior Firmware Engineer"]
    j = jobs[0]
    assert j.uid.startswith("simplify:") and j.uid.endswith(":" + load_fixture("simplify_listings.json")[0]["id"])
    assert j.source == "simplify" and j.company_size is None
    assert j.locations == ["Austin, TX"] and j.remote is False
    assert j.posted_at.endswith("Z") and j.tags == ["simplify"]
    assert "us-citizen-required" in jobs[1].tags


def test_greenhouse_parse():
    jobs = greenhouse.parse(load_fixture("greenhouse_gitlab.json"), GH)
    assert len(jobs) == 4
    j = jobs[2]
    assert j.uid == "greenhouse:gitlab:8771512002"
    assert j.title == "Backend Engineer, GitLab Orbit"
    assert j.locations == ["Remote, Canada", "Remote, United States"]
    assert j.remote is True
    assert j.url == "https://job-boards.greenhouse.io/gitlab/jobs/8771512002"
    assert j.posted_at == "2026-10-23T22:47:07Z"
    assert j.meta["posted_at_field"] == "first_published"
    assert jobs[3].meta["posted_at_field"] == "updated_at"
    assert jobs[3].posted_at == "2026-11-10T15:45:04Z"
    assert j.company_size == "M" and j.tags == ["watchlist"]


def test_lever_parse():
    jobs = lever.parse(load_fixture("lever_palantir.json"), LV)
    fellowship = jobs[0]
    assert fellowship.uid == "lever:palantir:0ccbe620-a3ef-41d1-a5c4-68e56b3c91d0"
    assert fellowship.title == "American Tech Fellowship"
    assert fellowship.remote is True  # workplaceType == remote
    assert fellowship.locations == ["North America"]
    assert fellowship.url.startswith("https://jobs.lever.co/palantir/")
    assert fellowship.posted_at == "2025-06-17T00:16:14Z"
    assert jobs[1].remote is False and jobs[1].locations == ["Singapore, Singapore"]


def test_ashby_parse():
    data = load_fixture("ashby_ramp.json")
    data["jobs"].append(dict(data["jobs"][0], id="unlisted", isListed=False))
    jobs = ashby.parse(data, AB)
    assert len(jobs) == 3  # unlisted skipped
    j = jobs[0]
    assert j.title == "Software Engineer, Security, Cloud"  # whitespace trimmed
    assert j.locations[0] == "New York, NY (HQ)" and "Remote (US)" in j.locations
    assert j.remote is True
    assert j.posted_at == "2026-04-07T17:12:35Z"
    assert j.url == "https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245"


def test_workday_parse():
    jobs = workday.parse(load_fixture("workday_chevron_university.json"), WD, "University", TODAY, TZ)
    assert len(jobs) == 5
    j = jobs[0]
    assert j.uid == "workday:chevron:R000072376"
    assert j.locations == []  # "4 Locations" needs the detail call
    assert j.url == ("https://chevron.wd5.myworkdayjobs.com/University/job/Richmond-California-United-States-"
                     "of-America/XMLNAME-2026-2027-Facilities-Engineering-Operations-and-Turnarounds-"
                     "Construction-Engineering-Intern_R000072376")
    assert j.posted_at.startswith("2026-11-11") and j.meta["posted_at_approx"] is True
    assert jobs[3].locations == ["Houston, Texas, United States of America"]
    assert jobs[1].posted_at.startswith("2026-10-18")  # 30+ days -> 31


def test_workday_detail_locations():
    locs = workday.detail_locations(load_fixture("workday_chevron_detail.json"))
    assert locs[0] == "Richmond, California, United States of America"
    assert "Midland, Texas, United States of America" in locs and len(locs) == 4


def test_workday_uid_falls_back_to_path():
    p = {"title": "Software Engineer", "externalPath": "/job/Houston/Software-Engineer_X", "locationsText": "Houston, TX",
         "postedOn": "Posted Today", "bulletFields": ["Houston, TX"]}
    j = workday.parse_posting(p, WD, "jobs", TODAY, TZ)
    assert j.uid == "workday:chevron:/job/Houston/Software-Engineer_X"
