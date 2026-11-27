from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "nowcasting_v3"))

from nyfed.au.finality import lock_active, release_slot


def main():
    data = ROOT / "data"
    now = datetime.now(timezone.utc)
    combo = json.loads((data / "latest_combo.json").read_text())
    gdp = json.loads((data / "gdp.json").read_text())["series"]
    slot = release_slot(json.loads((data / "latest.json").read_text()), now)
    already_ran = slot and (combo.get("final_estimate") or {}).get("run_date") == slot["run_date"]
    if not slot or (already_ran and lock_active(combo, gdp, now)) or any(
            row.get("quarter") == slot["quarter"] for row in gdp):
        return
    print(slot["run_date"])


if __name__ == "__main__":
    main()
