"""Synthetic live API smoke test; uses Meta and Bambu CLI, never printer APIs.

Run from project root with the app already running:
    .venv/Scripts/python.exe -m scripts.e2e_live
Creates a labeled synthetic job, local reservations, and a simulated outage.
Only sanitized evidence is written to the report; credentials stay in the server.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from backend.pricing import RateCard, calculate


def main():
    root = Path(__file__).resolve().parents[1]
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "physical_printer_contacted": False,
    }

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)
        print("PASS:", name, flush=True)

    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=55) as client:

        def post(path, body):
            r = client.post(path, json=body)
            if not r.is_success:
                try:
                    detail = r.json().get("detail", "Request failed")
                except ValueError:
                    detail = "Invalid response"
                raise RuntimeError(f"{path}: HTTP {r.status_code}: {detail}")
            return r.json()

        def state():
            r = client.get("/api/state")
            r.raise_for_status()
            return r.json()

        meta = client.get("/api/integrations").json()["meta"]
        check("Meta configured", meta["configured"])
        rates = client.get("/api/pricing").json()
        check("Shop pricing active", rates["mode"] == "shop")
        active_rates = RateCard.model_validate(rates["rates"])
        check("Shop rate card validates", bool(active_rates.currency))
        deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        request = f"Synthetic E2E test only. One PLA sample block. Required completion: {deadline}. No special finishing. STL units have not been specified."
        incomplete = post("/api/intake/drafts", {"request": request})
        check(
            "Live Meta asks for missing STL units",
            incomplete["source"] == "meta_model_api"
            and incomplete["draft"]["units"] is None
            and "units" in incomplete["missing_fields"],
        )
        complete = request.replace(
            "STL units have not been specified.", "The STL units are millimeters."
        )
        draft = post("/api/intake/drafts", {"request": complete})
        d = draft["draft"]
        check(
            "Live Meta extracts confirmed requirements",
            d["quantity"] == 1
            and d["material"].upper() == "PLA"
            and d["units"] == "mm"
            and bool(d["deadline"]),
        )
        job = post(
            "/api/jobs",
            dict(
                title="E2E synthetic / Meta to X2D recovery",
                request=complete,
                quantity=d["quantity"],
                material="PLA",
                units=d["units"],
                deadline=d["deadline"],
                intake_draft_id=draft["id"],
                ai_review_confirmed=True,
            ),
        )
        report["job_id"] = job["id"]
        report["model"] = draft["model"]
        report["rate_card"] = rates["id"]
        jid = job["id"]
        with (root / "samples/demo-block.stl").open("rb") as mesh:
            response = client.post(
                "/api/jobs/" + jid + "/file",
                files={"file": ("demo-block.stl", mesh, "application/octet-stream")},
            )
            response.raise_for_status()
        check("STL upload validated", response.json()["file"]["watertight"])
        task = post(
            "/api/jobs/" + jid + "/slice-quotes",
            dict(
                profile_id="x2d-pla-0.4-v1",
                confirmed=True,
                idempotency_key=uuid.uuid4().hex,
                support_percent=0,
                apply_support_surcharge=False,
            ),
        )
        until = time.monotonic() + 140
        while time.monotonic() < until:
            task = client.get("/api/tasks/" + task["id"]).json()
            if task["status"] not in ("queued", "running"):
                break
            time.sleep(0.5)
        check("Native X2D slicing succeeded", task["status"] == "succeeded")
        quote = next(q for q in state()["quotes"] if q["id"] == task["quote_id"])
        source = client.get("/api/tasks/" + task["id"] + "/report").json()[
            "sliced_plates"
        ][0]
        check(
            "X2D slot preserved and single-filament slice",
            source["filaments"][0]["id"] == 2
            and len(source["filaments"]) == 1
            and source["filament_change_times"] == 0,
        )
        check(
            "Shop rates and minimum used",
            quote["rate_card"] == rates["id"]
            and quote["pricing_mode"] == "shop"
            and quote["total_cents"]
            == calculate(
                quote["grams"], quote["hours"], active_rates, support_percent=0
            )["total_cents"]
            and not quote["support_review_required"],
        )
        proposal = post("/api/jobs/" + jid + "/proposals", None)
        check(
            "Compatible X2D slot proposed",
            proposal["choice"]["printer_id"] == "bambu-x2d"
            and proposal["choice"]["on_time"],
        )
        approval_key = uuid.uuid4().hex
        first = post(
            "/api/proposals/" + proposal["id"] + "/approve",
            {"idempotency_key": approval_key},
        )
        repeat = post(
            "/api/proposals/" + proposal["id"] + "/approve",
            {"idempotency_key": approval_key},
        )
        old = first["reservation"]
        check("Initial approval is idempotent", repeat == first)
        outage_data = dict(
            printer_id="bambu-x2d",
            starts_at=old["start"],
            ends_at=old["end"],
            reason="Synthetic E2E pre-start outage; no physical printer action",
            event_key=uuid.uuid4().hex,
        )
        outage = post("/api/outages", outage_data)
        check("Outage affects only the synthetic job", outage["affected_jobs"] == [jid])
        check(
            "Duplicate outage event is idempotent",
            post("/api/outages", outage_data)["id"] == outage["id"],
        )
        before = state()
        check(
            "Original reservation retained pending recovery",
            next(r for r in before["reservations"] if r["id"] == old["id"])["active"],
        )
        recovery = post("/api/jobs/" + jid + "/recovery", None)
        check(
            "Recovery rebooks compatible X2D after outage",
            recovery["choice"]["printer_id"] == "bambu-x2d"
            and datetime.fromisoformat(
                recovery["choice"]["start"].replace("Z", "+00:00")
            )
            >= datetime.fromisoformat(outage["ends_at"].replace("Z", "+00:00"))
            and recovery["quote_id"] == quote["id"],
        )
        check("Customer update is a draft", bool(recovery["message_draft"]))
        result = post(
            "/api/proposals/" + recovery["id"] + "/approve",
            {"idempotency_key": uuid.uuid4().hex},
        )
        after = state()
        reservations = [r for r in after["reservations"] if r["job_id"] == jid]
        check(
            "Recovery atomically replaces the old reservation",
            sum(r["active"] for r in reservations) == 1
            and not next(r for r in reservations if r["id"] == old["id"])["active"]
            and result["job"]["status"] == "scheduled",
        )
        check(
            "Recovery preserves the original quote and price",
            next(q for q in after["quotes"] if q["id"] == quote["id"]) == quote,
        )
        audit = [a["event"] for a in after["audit"] if a["job_id"] == jid]
        check(
            "Workflow audit contains each committed transition",
            all(
                e in audit
                for e in [
                    "job_created",
                    "mesh_validated",
                    "quote_created",
                    "plan_approved",
                    "printer_unavailable",
                    "recovery_proposed",
                    "recovery_approved",
                ]
            ),
        )
        active = [
            r
            for r in after["reservations"]
            if r["active"] and r["printer_id"] == "bambu-x2d"
        ]
        check(
            "No overlapping active X2D reservations",
            all(
                not (
                    datetime.fromisoformat(a["start"].replace("Z", "+00:00"))
                    < datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                    and datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                    < datetime.fromisoformat(a["end"].replace("Z", "+00:00"))
                )
                for i, a in enumerate(active)
                for b in active[i + 1 :]
            ),
        )
        report.update(
            status="passed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            price={"currency": quote["currency"], "total_cents": quote["total_cents"]},
            slice={
                "grams": quote["grams"],
                "seconds": quote["slicer"]["seconds_per_part"],
                "profile": quote["profile"],
            },
            original_reservation=old,
            recovered_reservation=result["reservation"],
            audit_events=audit,
            customer_message_sent=False,
        )
    output = root / "output" / "tests"
    output.mkdir(parents=True, exist_ok=True)
    (output / "e2e-live-result.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        "Live E2E passed; sanitized evidence saved to output/tests/e2e-live-result.json",
        flush=True,
    )


if __name__ == "__main__":
    main()
