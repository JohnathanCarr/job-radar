"""Title, location and age filters, driven by config/filters.yaml."""

from __future__ import annotations

import re
from datetime import date, datetime

from .models import Job, is_remote_text

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
_STATE_NAME_RE = re.compile(r"(?i),\s*(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")\b")
_STATE_ABBR_RE = re.compile(r",\s*(" + "|".join(sorted(set(US_STATES.values()))) + r")\b|^US\s*-")
_US_RE = re.compile(r"(?i:\b(united states|usa|nationwide)\b|\bu\.s\.)|\bUS\b")
_FOREIGN_RE = re.compile(
    r"(?i)\b(canada|canadian|mexico|uk|united kingdom|england|scotland|ireland|europe|emea|apac|"
    r"latam|latin america|india|germany|france|spain|portugal|poland|netherlands|brazil|argentina|"
    r"colombia|chile|philippines|singapore|japan|australia|israel|romania|costa rica|ukraine|"
    r"toronto|vancouver|montreal|london|bengaluru|bangalore|hyderabad|berlin|dublin|amsterdam)\b"
)

LOC_RANK = {"loc-preferred": 0, "loc-acceptable": 1, "other-us": 2}


def normalize_location(text: str) -> str:
    """'Spring, Texas, United States' -> 'Spring, TX, United States' for regex matching."""
    return _STATE_NAME_RE.sub(lambda m: ", " + US_STATES[m.group(1).lower()], text)


def is_us(text: str) -> bool:
    t = normalize_location(text)
    return bool(_US_RE.search(t) or _STATE_ABBR_RE.search(t))


def is_foreign(text: str) -> bool:
    return bool(_FOREIGN_RE.search(text)) and not is_us(text)


class Filters:
    def __init__(self, cfg: dict):
        t = cfg["title"]
        self.t_include = re.compile(t["include"])
        self.t_include_also = re.compile(t["include_also"])
        self.t_exclude = re.compile(t["exclude"])
        self.t_exclude_hw = re.compile(t["exclude_hardware"]) if t.get("exclude_hardware") else None
        self.t_level = re.compile(t["level_exclude_unless_entry"])
        self.t_entry = re.compile(t["level_entry_markers"])

        loc = cfg["location"]
        self.l_preferred = [re.compile(p) for p in loc["preferred"]]
        self.l_acceptable = [re.compile(p) for p in loc["acceptable"]]
        self.include_other_us = bool(loc.get("include_other_us", False))
        self.remote_must_be_us = bool(loc.get("remote_must_be_us", True))

        age = cfg["age"]
        self.max_days = int(age["max_days"])
        self.keep_undated = bool(age.get("keep_undated", True))

    # --- title ---------------------------------------------------------
    def title_ok(self, title: str) -> bool:
        t = title.strip()
        if self.t_exclude.search(t):
            return False
        if self.t_exclude_hw and self.t_exclude_hw.search(t):
            return False
        if not (self.t_include.search(t) or self.t_include_also.search(t)):
            return False
        if self.t_level.search(t) and not self.t_entry.search(t):
            return False
        return True

    # --- location ------------------------------------------------------
    def _classify_one(self, raw: str) -> str | None:
        text = normalize_location(raw)
        if is_remote_text(text) and self.remote_must_be_us and is_foreign(text):
            return None
        if any(p.search(text) for p in self.l_preferred):
            return "loc-preferred"
        if any(p.search(text) for p in self.l_acceptable):
            return "loc-acceptable"
        if is_us(text):
            return "other-us"
        return None

    def location_tag(self, job: Job) -> str | None:
        """Best location tag for the job, or None if it should be dropped."""
        tags = [self._classify_one(loc) for loc in job.locations]
        # A source-level remote flag (Ashby isRemote, Lever workplaceType) with US or no
        # locations counts as remote-US even when no location string says "Remote".
        if job.remote and not any(is_remote_text(l) for l in job.locations):
            if not job.locations or any(is_us(l) for l in job.locations) or not self.remote_must_be_us:
                tags.append("loc-preferred")
        tags = [t for t in tags if t]
        if not tags:
            return None
        best = min(tags, key=LOC_RANK.__getitem__)
        if best == "other-us" and not self.include_other_us:
            return None
        return best

    # --- age -----------------------------------------------------------
    def age_ok(self, job: Job, today: date, tz) -> bool:
        if not job.posted_at:
            return self.keep_undated
        posted = datetime.fromisoformat(job.posted_at.replace("Z", "+00:00")).astimezone(tz).date()
        return (today - posted).days <= self.max_days

    # --- all -----------------------------------------------------------
    def apply(self, job: Job, today: date, tz) -> bool:
        """Return True to keep. Adds the location tag to job.tags."""
        if not self.title_ok(job.title):
            return False
        tag = self.location_tag(job)
        if tag is None:
            return False
        if not self.age_ok(job, today, tz):
            return False
        job.tags = sorted(set(job.tags) | {tag})
        return True
