"""Create a fresh, isolated rehearsal DB using the live app's current shop rates.

Called by start_demo.ps1 before launching a separate server. No live jobs are
copied or edited. Credentials remain in .env and are not written to the prompt.
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


def prepare():
    root = Path(__file__).resolve().parents[1]
    # Require the operator's live pricing; never substitute remembered/demo values.
    with httpx.Client(timeout=10) as client:
        response = client.get("http://127.0.0.1:8765/api/pricing")
        response.raise_for_status()
        card = response.json()
    if card.get("mode") != "shop":
        raise RuntimeError("Save shop rates in the main app before preparing the demo.")
    directory = root / "data" / "demo-sessions" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    os.environ["DATA_DIR"] = str(directory)
    os.environ["DATABASE_URL"] = "sqlite:///" + (directory / "shop.db").as_posix()
    from backend import main

    with main.transaction() as connection:
        main.put(connection, "rate_card", card)
        if main.rows(connection, "job") or main.rows(connection, "reservation"):
            raise RuntimeError("Expected an empty rehearsal database.")
    zone = ZoneInfo(os.getenv("SHOP_TIMEZONE", "America/New_York"))
    deadline = (datetime.now(zone) + timedelta(days=3)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    request = f"Please quote one PLA calibration block. Completion deadline: {deadline.isoformat()}. No special finishing. The STL units have not been specified."
    (directory / "intake-prompt.txt").write_text(request + "\n", encoding="utf-8")
    (directory / "shop-rate-card.json").write_text(
        json.dumps(card, indent=2), encoding="utf-8"
    )
    main.engine.dispose()
    # PowerShell consumes only this path; no key or credential value is printed.
    print(directory)


if __name__ == "__main__":
    prepare()
