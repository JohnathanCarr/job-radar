from datetime import datetime, timedelta, timezone

import pytest

from radar.suggest import detect_ats, suggest

NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
CATS = {"Software", "AI/ML/Data"}


@pytest.mark.parametrize("url,expected", [
    ("https://job-boards.greenhouse.io/affirm/jobs/8181183003", {"ats": "greenhouse", "slug": "affirm"}),
    ("https://boards.greenhouse.io/embed/job_app?for=toyotaconnected&token=1", {"ats": "greenhouse", "slug": "toyotaconnected"}),
    ("https://jobs.lever.co/waabi/abc-123", {"ats": "lever", "slug": "waabi"}),
    ("https://jobs.ashbyhq.com/zetta2/28a4/application", {"ats": "ashby", "slug": "zetta2"}),
    ("https://q2ebanking.wd5.myworkdayjobs.com/Q2/job/Austin-TX/Software-Engineer_REQ-1",
     {"ats": "workday", "tenant": "q2ebanking", "wd": 5, "site": "Q2"}),
    ("https://bpinternational.wd3.myworkdayjobs.com/en-US/bpCareers/job/x",
     {"ats": "workday", "tenant": "bpinternational", "wd": 3, "site": "bpCareers"}),
    ("https://apply.workable.com/x/j/AB12", None),
])
def test_detect_ats(url, expected):
    assert detect_ats(url) == expected


def rec(company, url, locations, days_ago=5, category="Software", active=True, title="Software Engineer"):
    return {"company_name": company, "url": url, "locations": locations, "category": category,
            "active": active, "is_visible": True, "title": title,
            "date_posted": int((NOW - timedelta(days=days_ago)).timestamp())}


def test_suggest():
    records = [
        rec("Q2", "https://q2ebanking.wd5.myworkdayjobs.com/Q2/job/a_1", ["Austin, TX"]),
        rec("Q2", "https://q2ebanking.wd5.myworkdayjobs.com/en-US/Q2/job/b_2", ["Remote in USA"]),
        rec("Affirm", "https://job-boards.greenhouse.io/affirm/jobs/1", ["Remote in USA"]),
        rec("Watched", "https://jobs.lever.co/waabi/1", ["Dallas, TX"]),                       # in watchlist
        rec("Old", "https://jobs.lever.co/old/1", ["Houston, TX"], days_ago=90),               # too old
        rec("Canada", "https://jobs.lever.co/ca/1", ["Remote in Canada"]),                     # not US
        rec("Boston", "https://jobs.lever.co/bos/1", ["Boston, MA"]),                          # not TX
        rec("Hardware", "https://jobs.lever.co/hw/1", ["Austin, TX"], category="Hardware"),    # category
        rec("Workable", "https://apply.workable.com/w/j/1", ["Austin, TX"]),                   # unsupported ATS
        rec("Inactive", "https://jobs.lever.co/in/1", ["Austin, TX"], active=False),
    ]
    watchlist = [{"name": "Waabi", "ats": "lever", "slug": "waabi"}]
    stubs = suggest(records, CATS, watchlist, NOW)
    assert [s["name"] for s in stubs] == ["Q2", "Affirm"]
    q2 = stubs[0]
    assert q2["ats"] == "workday" and q2["tenant"] == "q2ebanking" and q2["wd"] == 5 and q2["site"] == "Q2"
    assert q2["why"].startswith("Simplify: 2 ")
    assert stubs[1] == {"name": "Affirm", "ats": "greenhouse", "slug": "affirm", "size": None, "city": None,
                        "why": "Simplify: 1 TX/remote-US software role(s) in 60d, e.g. 'Software Engineer'"}
    assert [s["name"] for s in suggest(records, CATS, watchlist, NOW, minimum=2)] == ["Q2"]
