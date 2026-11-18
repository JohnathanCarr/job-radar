# job-radar

Polls company ATS job boards (Greenhouse, Lever, Ashby, Workday) and the SimplifyJobs
new-grad dataset once a day. Publishes only roles that match the title/location/age filters
and that this repo hasn't seen before. A job's freshness is the date its ID first appeared here,
not a job board's "posted" date.

No LLM calls, scoring, or personal data. Output is read by a separate triage task from
`https://raw.githubusercontent.com/<owner>/job-radar/main/data/new.json`.

## Run

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m radar.main              # normal daily run
python -m radar.main --bootstrap  # fill seen/jobs; new.json gets only jobs posted in the last 7 days
python -m radar.main --only greenhouse   # debug: feeds whose key contains the text
pytest
python -m radar.suggest --days 60 --min 1   # print watchlist.yaml stubs from the Simplify dataset
```

`radar.suggest` lists companies with Texas or remote-US software roles on Simplify in the last
N days whose posting URLs are on Greenhouse, Lever, Ashby or Workday, skipping companies already
on the watchlist. It prints YAML stubs. Fill in `size`/`city`/`why`, and check the endpoint
before adding one.

If `data/seen.json` doesn't exist, the run bootstraps automatically.

GitHub Actions (`.github/workflows/radar.yml`) runs daily at 11:00 UTC (05:00 CST / 06:00 CDT),
commits `data/` as `radar: YYYY-MM-DD (+N new)`, and fails the job (after committing) when more
than half of the feeds error. Run it manually from the Actions tab; the `bootstrap` input does a
bootstrap run.

## Output (`data/`)

| File | Contents |
|---|---|
| `new.json` | `{run_at, count, jobs: [...]}`: jobs first seen this run. Sorted by location tag (preferred first), then `posted_at` desc. Overwritten every run. |
| `jobs.json` | `{run_at, count, jobs: {uid: job}}`: every currently matching job, ordered by `first_seen` desc, then `posted_at` desc. |
| `seen.json` | `{uid: first_seen}`. Entries older than 120 days are pruned unless the job is still live. |
| `run_log.json` | Per feed: `fetched`, `kept`, `new`, `error`; plus totals and runtime. |

Job fields follow the triage contract (brief §11): `uid, source, company, title, locations, remote,
url, posted_at, first_seen, company_size, tags`. One field was added: `meta`, a dict of provenance
fields (`feed`, `posted_at_field`, `posted_at_approx`, `alt_uids`, Simplify `category`/`degrees`/
`sponsorship`). Triage can ignore it.

Tags: `watchlist`, `simplify`, one of `loc-preferred` / `loc-acceptable` / `other-us`, and the
Simplify sponsorship tags `us-citizen-required`, `no-sponsorship`, `offers-sponsorship`.

## Config

- `config/watchlist.yaml`: companies polled directly. Workday `site` can be a list.
- `config/filters.yaml`: title/location/age rules.
- `config/unsupported.yaml`: companies on iCIMS/Oracle/SuccessFactors, to check by hand.

## Where live data differed from the brief (verified 2026-11-18)

- **Greenhouse**: `content=true` is not used. `first_published` and `updated_at` come back
  without it, and descriptions add many MB per run (SpaceX has ~2.8k jobs). `absolute_url` is now
  usually `job-boards.greenhouse.io/...`. Some boards put several locations in one string
  separated by `;` or `|`; these are split.
- **Ashby**: titles can have leading/trailing whitespace (trimmed). `isRemote` can be true for
  jobs whose primary location is an office. A remote flag counts as remote-US only when a
  location is in the US (or none is listed).
- **Workday**: `locationsText` is `"N Locations"` for multi-location jobs. For those, the radar
  fetches the job detail (`GET .../wday/cxs/{tenant}/{site}{externalPath}` → `location` +
  `additionalLocations`), but only when the title passes the filter. `total` is only reliable on
  the first page. `posted_at` is derived from relative text (marked `posted_at_approx`), and the
  earliest value recorded for a uid is kept so it doesn't drift.
  **Workday returns HTTP 429 to automated clients.** From this dev container and from GitHub
  Actions, 7 of 8 tenants refused requests, including with a browser User-Agent (tried and
  reverted). Only Sentry answers, so it is the only Workday feed left; the rest are in
  `unsupported.yaml`. The Workday source stays in the code for any tenant that allows access.
- **Simplify**: matches the brief. One extra sponsorship value: `Offers Sponsorship`.

## Changes to the brief's filter config

- Location regexes are wrapped in `\b...\b`. Without boundaries, `addison` matched "Madison, WI".
- Title `include` adds `sw` (Visa posts "SW Engineer").
- New `title.exclude_hardware` regex (silicon, ASIC, FPGA, RTL, mechanical, electrical, ...).
- Cross-source dedupe also strips a trailing `/apply` or `/application` from URLs (Simplify
  often links the application page, the ATS links the posting).

## Open issues

- Most Workday tenants block automated access (see above). Visa, Chevron, BP, Insperity, PROS,
  Memorial Hermann and Westlake are in `unsupported.yaml` for manual checks.
- NOV (Oracle), Kinder Morgan (iCIMS), NRG and Phillips 66 (SuccessFactors) aren't on a
  supported ATS; they are in `unsupported.yaml`.
