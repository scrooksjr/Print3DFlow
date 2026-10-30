"""Execution readiness only. No network connector or physical command capability."""
import hashlib
import json
from datetime import timedelta
from typing import Literal

from backend import printer_connector
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["manual", "assisted", "automatic"]
    confirmed: Literal[True]


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: str
    artifact_reviewed: Literal[True]
    filament_loaded: Literal[True]
    sufficient_material: Literal[True]
    plate_clear: Literal[True]
    printer_ready: Literal[True]
    confirmed: Literal[True]


def register(app):
    from backend import main as m

    def policy(c, printer_id):
        found = next((p for p in m.rows(c, "execution_policy") if p["printer_id"] == printer_id), None)
        return found or dict(id="execution-policy-" + printer_id, printer_id=printer_id, mode="manual")

    def readiness(c, job_id):
        job = m.get(c, job_id, "job")
        reservation = m.get(c, job["reservation_id"], "reservation") if job.get("reservation_id") else None
        printer = m.get(c, reservation["printer_id"], "printer") if reservation else None
        quote = m.get(c, job["latest_quote_id"], "quote") if job.get("latest_quote_id") else None
        selected = policy(c, printer["id"]) if printer else None
        blockers = []
        if not reservation or not reservation.get("active") or job["status"] != "scheduled":
            blockers.append("An active, approved reservation on a scheduled job is required.")
        if reservation and (reservation.get("job_id") != job_id or reservation.get("quote_id") != job.get("latest_quote_id")):
            blockers.append("Reservation and selected quote no longer match.")
        if not quote or quote.get("source") not in ("bambu_studio", "bambu_multicolor"):
            blockers.append("A native slicer-backed quote is required for assisted readiness review.")
        elif job["status"] == "scheduled":
            try:
                m.valid_quote(c, job)
            except HTTPException:
                blockers.append("Quote evidence expired or changed; review and regenerate it.")
        outages = [o for o in m.rows(c, "outage") if printer and o["printer_id"] == printer["id"]]
        if reservation:
            if m.parse(reservation["end"]) <= m.now():
                blockers.append("The reserved time has elapsed; review scheduling.")
            if any(m.overlaps(m.parse(reservation["start"]), m.parse(reservation["end"]), m.parse(o["starts_at"]), m.parse(o["ends_at"])) for o in outages):
                blockers.append("A recorded outage conflicts with this reservation.")
        if printer and not printer.get("active", True):
            blockers.append("Printer is inactive.")
        connection = printer_connector.status(m, c, printer["id"]) if printer else dict(connected=False, status="not_configured", source="no_live_telemetry")
        if selected and selected["mode"] == "assisted" and connection["status"] != "not_configured" and not connection["connected"]:
            blockers.append("Configured printer telemetry is unavailable or stale; check the connection again.")
        if connection["connected"]:
            telemetry = connection.get("telemetry", {})
            if telemetry.get("state") not in ("IDLE", "FINISH"):
                blockers.append("Printer telemetry does not report an idle or finished state.")
            if telemetry.get("error_present") or not telemetry.get("error_known"):
                blockers.append("Printer error state is present or unknown; inspect locally.")
        basis = dict(connection=connection, job=job, quote=quote, reservation=reservation, printer=printer, policy=selected, outages=outages)
        fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        reviews = [r for r in m.rows(c, "execution_review") if r["job_id"] == job_id]
        reviews.sort(key=lambda r: r["created_at"])
        last = reviews[-1] if reviews else None
        current = bool(last and last["snapshot"] == fingerprint and m.parse(last["expires_at"]) > m.now() and not blockers)
        return dict(snapshot=fingerprint, printer_id=printer["id"] if printer else None, policy=selected,
                    blockers=blockers, review_current=current, last_review=last,
                    connection=connection,
                    remote_start_allowed=False, automatic_execution_allowed=False,
                    next_step="Start manually at the printer after your own final checks." if current else "Resolve blockers and confirm physical readiness.")

    @app.get("/api/jobs/{job_id}/execution")
    def execution_readiness(job_id: str):
        with m.engine.connect() as c:
            return readiness(c, job_id)

    @app.post("/api/printers/{printer_id}/execution-policy")
    def save_policy(printer_id: str, body: Policy):
        with m.transaction() as c:
            m.get(c, printer_id, "printer")
            if body.mode == "automatic":
                m.fail("Automatic execution requires a verified printer connector and command acknowledgement; no policy changed.")
            obj = policy(c, printer_id)
            obj.update(mode=body.mode, updated_at=m.stamp())
            m.put(c, "execution_policy", obj)
            m.audit(c, None, "execution_policy_updated", dict(printer_id=printer_id, mode=body.mode, remote_start_allowed=False))
            return obj

    @app.post("/api/jobs/{job_id}/execution-review")
    def save_review(job_id: str, body: Review):
        with m.transaction() as c:
            state = readiness(c, job_id)
            if state["snapshot"] != body.snapshot:
                m.fail("Readiness evidence changed. Refresh and review again.")
            if state["blockers"]:
                m.fail("Resolve execution readiness blockers before recording review.")
            obj = dict(id=m.uid(), job_id=job_id, snapshot=body.snapshot,
                       checks=body.model_dump(exclude={"snapshot"}), source="operator_attestation_not_telemetry",
                       created_at=m.stamp(), expires_at=(m.now() + timedelta(minutes=10)).isoformat())
            m.put(c, "execution_review", obj)
            m.audit(c, job_id, "execution_readiness_reviewed", dict(review_id=obj["id"], printer_commands_sent=False))
            return readiness(c, job_id)
