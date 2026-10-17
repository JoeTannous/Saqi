"""Pull new Sentinel-2 passes for every block with a boundary. Run daily by a GitHub Action.

    DATABASE_URL=... SH_CLIENT_ID=... SH_CLIENT_SECRET=... python -m api.sync_satellite

First run backfills 120 days per block; later runs re-read the last 15 days
(a pass can arrive a day or two late) and refresh the NDVI map when a newer clear
pass exists.
"""

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from api.fieldstore import FieldStore, PostgresFieldStore
from api.ids import slug
from api.satellite import SentinelHub
from engine.cli import load_farm
from engine.fieldhealth import usable
from engine.models import Boundary

ROOT = Path(__file__).resolve().parent.parent
BACKFILL_DAYS = 120
OVERLAP_DAYS = 15


def farm_files() -> list[Path]:
    farms = sorted((ROOT / "farms").glob("*.yaml"))
    return farms or sorted((ROOT / "examples").glob("*.yaml"))


def sync_block(farm_id: str, block_id: str, boundary: Boundary, today: date,
               store: FieldStore, hub: SentinelHub, now: datetime) -> str:
    known = store.observations(farm_id, block_id, today - timedelta(days=BACKFILL_DAYS))
    start = (known[-1].date - timedelta(days=OVERLAP_DAYS) if known
             else today - timedelta(days=BACKFILL_DAYS))
    fresh = hub.observations(boundary, start, today)
    store.save_observations(farm_id, block_id, fresh, now)

    clear = usable(store.observations(farm_id, block_id, today - timedelta(days=BACKFILL_DAYS)))
    mapped = store.latest_map(farm_id, block_id)
    note = ""
    if clear and (mapped is None or clear[-1].date > mapped.date):
        png = hub.ndvi_png(boundary, clear[-1].date)
        store.save_map(farm_id, block_id, clear[-1].date, png, now)
        note = f", map {clear[-1].date.isoformat()}"
    return f"{farm_id}/{block_id}: {len(fresh)} passes since {start.isoformat()}{note}"


def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    store = PostgresFieldStore(url)
    store.ensure_schema()
    now = datetime.now(UTC)
    failures = 0
    with httpx.Client(timeout=120.0, headers={"User-Agent": "saqi-sync/0.1"}) as http:
        hub = SentinelHub.from_env(http)
        if hub is None:
            print("SH_CLIENT_ID / SH_CLIENT_SECRET are not set; skipping satellite sync")
            return 0
        for path in farm_files():
            config = load_farm(path)
            for block in config.blocks:
                if block.boundary is None:
                    continue
                try:
                    print(sync_block(path.stem, slug(block.name), block.boundary,
                                     config.today, store, hub, now))
                except Exception as exc:  # one block must not stop the others
                    failures += 1
                    print(f"{path.stem}/{slug(block.name)}: FAILED {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
