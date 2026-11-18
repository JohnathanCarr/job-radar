import json
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.filters import Filters  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("America/Chicago")
TODAY = date(2026, 11, 18)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="session")
def filters_cfg():
    return yaml.safe_load((ROOT / "config" / "filters.yaml").read_text())


@pytest.fixture(scope="session")
def filters(filters_cfg):
    return Filters(filters_cfg)
