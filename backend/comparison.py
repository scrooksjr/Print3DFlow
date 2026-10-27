"""Independent slices and quotes; no commitment until explicit comparison approval."""

import copy
import hashlib
import json
import os
from datetime import timedelta

import httpx
from fastapi import BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from backend import integrations


class CompareRequest(BaseModel):
    confirmed: Literal[True]
    profile_ids: list[str] = Field(min_length=1, max_length=3)
    support_percent_by_profile: dict[str, float] = Field(default_factory=dict)


class CommitRequest(BaseModel):
    option_id: str
    total_cents: int
    currency: str
    confirmed: Literal[True]
    idempotency_key: str = Field(min_length=8, max_length=100)


class ExplainRequest(BaseModel):
    consent_to_send_quote_totals: Literal[True]


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str
    reason_codes: list[str] = Field(min_length=1, max_length=8)


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommended_option_id: str | None
    assessments: list[Assessment] = Field(min_length=1, max_length=20)


REASONS = {
    "meets_deadline": "Completes within the requested deadline.",
    "misses_deadline": "Misses the requested deadline; cannot be approved.",
    "earliest_completion": "Has the earliest verified completion among these options.",
    "lowest_price": "Has the lowest verified quote among these options.",
    "same_printer": "Keeps the originally reserved printer.",
    "switch_printer": "Requires moving the job to a different printer.",
    "price_increase": "Increases the current quote; explicit price approval is required.",
    "price_decrease": "Reduces the current quote; explicit price approval is required.",
    "unchanged_price": "Keeps the current quote total.",
    "support_review": "Support percentage must be reviewed before this quote can be approved.",
}


def fingerprint(m, c, job, profile_ids):
    profiles = {}
    for pid in profile_ids:
        try:
            profiles[pid] = integrations.load_profile(pid)[2]
        except integrations.IntegrationError:
            profiles[pid] = "unavailable"
    payload = dict(
        job=job,
        profiles=profiles,
        rates=m.current_rates(c),
        printers=m.rows(c, "printer"),
        reservations=[r for r in m.rows(c, "reservation") if r["active"]],
        outages=m.rows(c, "outage"),
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def verify(m, c, batch):
    job = m.get(c, batch["job_id"], "job")
    if batch["status"] != "ready" or m.parse(batch["expires_at"]) <= m.now():
        m.fail("Comparison is expired or not ready; compare again")
    if fingerprint(m, c, job, batch["profile_ids"]) != batch["snapshot_hash"]:
        m.fail(
            "Comparison is stale because the job, rates, profile or capacity changed; compare again"
        )
    for option in batch["options"]:
        if m.parse(option["start"]) <= m.now():
            m.fail("Comparison start time has passed; compare again")
        q = m.get(c, option["quote_id"], "quote")
        if m.parse(q["expires_at"]) <= m.now():
            m.fail("Comparison quote expired; compare again")
        if integrations.load_profile(q["profile"])[2] != q["slicer"]["profile_sha256"]:
            m.fail("Comparison profile changed; compare again")
    return job


def worker(m, batch_id):
    try:
        with m.transaction() as c:
            batch = m.get(c, batch_id, "comparison")
            batch["status"] = "running"
            m.put(c, "comparison", batch)
            original = m.get(c, batch["job_id"], "job")
        slices, excluded = {}, []
        for pid in batch["profile_ids"]:
            try:
                result = integrations.run_bambu_slice(
                    m.DATA / (original["file"]["sha256"] + ".stl"),
                    original["units"],
                    pid,
                    m.DATA / "comparisons" / batch_id / pid,
                )
                if result["profile_sha256"] != batch["profile_hashes"][pid]:
                    raise integrations.IntegrationError(
                        "Profile changed while slicing; compare again."
                    )
                slices[pid] = result
            except integrations.IntegrationError as exc:
                excluded.append(dict(profile_id=pid, reason=str(exc)))
        with m.transaction() as c:
            job = m.get(c, original["id"], "job")
            if fingerprint(m, c, job, batch["profile_ids"]) != batch["snapshot_hash"]:
                m.fail("Inputs changed during slicing; compare again")
            options = []
            for pid, result in slices.items():
                s = result["settings"]
                estimate = m.Estimates(
                    grams_per_part=result["grams_per_part"],
                    hours_per_part=result["hours_per_part"],
                    confirmed=True,
                    layer_height_mm=s["layer_height_mm"],
                    infill_percent=s["infill_percent"],
                    walls=s["walls"],
                    supports=s["supports"],
                    support_percent=batch["support_percent_by_profile"].get(pid),
                )
                draft = copy.deepcopy(job)
                draft["status"] = "quote_ready"
                q = m.build_quote(c, draft, estimate, result)
                # Candidate creation must never replace the current/approved quote.
                m.put(c, "job", job)
                for slot in m.slots(c, job, q, job.get("reservation_id")):
                    options.append(
                        dict(
                            **slot,
                            option_id="option-" + str(len(options) + 1),
                            quote_id=q["id"],
                            profile_id=pid,
                            grams=q["grams"],
                            slicer_seconds=result["seconds_per_part"],
                            total_cents=q["total_cents"],
                            currency=q["currency"],
                            duration_minutes=q["duration_minutes"],
                            support_review_required=q["support_review_required"],
                            items=q["items"],
                        )
                    )
            if not options:
                m.fail("No successfully sliced compatible options; review exclusions")
            baseline = (
                m.get(c, job["latest_quote_id"], "quote")
                if job.get("latest_quote_id")
                else None
            )
            old = (
                m.get(c, job["reservation_id"], "reservation")
                if job.get("reservation_id")
                else None
            )
            for o in options:
                codes = ["meets_deadline" if o["on_time"] else "misses_deadline"]
                if o["end"] == min(x["end"] for x in options):
                    codes.append("earliest_completion")
                if o["total_cents"] == min(x["total_cents"] for x in options):
                    codes.append("lowest_price")
                if old:
                    codes.append(
                        "same_printer"
                        if o["printer_id"] == old["printer_id"]
                        else "switch_printer"
                    )
                o["price_delta_cents"] = (
                    o["total_cents"] - baseline["total_cents"] if baseline else None
                )
                if baseline and baseline["currency"] == o["currency"]:
                    codes.append(
                        "price_increase"
                        if o["price_delta_cents"] > 0
                        else "price_decrease"
                        if o["price_delta_cents"] < 0
                        else "unchanged_price"
                    )
                if o["support_review_required"]:
                    codes.append("support_review")
                o["valid_reason_codes"] = codes
            batch.update(
                status="ready",
                options=options,
                excluded=excluded,
                baseline_total_cents=baseline["total_cents"] if baseline else None,
                baseline_currency=baseline["currency"] if baseline else None,
            )
            m.put(c, "comparison", batch)
            m.audit(c, job["id"], "comparison_ready", {"comparison_id": batch_id})
    except Exception:
        with m.transaction() as c:
            batch = m.get(c, batch_id, "comparison")
            batch.update(
                status="failed",
                error="Comparison could not complete or inputs changed. Review settings and compare again.",
                excluded=locals().get("excluded", []),
            )
            m.put(c, "comparison", batch)


def ask_meta(batch):
    key = os.getenv("META_API_KEY", "").strip()
    model = os.getenv("META_MODEL", "muse-spark-1.3")
    if not key or "contributor" in model:
        raise integrations.IntegrationError(
            "Configure a Standard-mode Meta model to request advice."
        )
    context = [
        {
            k: o[k]
            for k in (
                "option_id",
                "grams",
                "slicer_seconds",
                "total_cents",
                "currency",
                "start",
                "end",
                "on_time",
                "support_review_required",
                "price_delta_cents",
                "valid_reason_codes",
            )
        }
        for o in batch["options"]
    ]
    prompt = (
        "Compare these independently sliced printer options with verified quote totals and schedules. "
        "Assess every option exactly once. Use only its valid_reason_codes; no freeform claims. "
        "Recommend an on-time option that does not require support review, balancing cost and completion time; "
        "otherwise recommend null. A recommendation changes nothing. All price and reservation changes require operator approval."
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(40, connect=10)) as client:
            response = client.post(
                "https://api.meta.ai/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json=dict(
                    model=model,
                    messages=[
                        {"role": "developer", "content": prompt},
                        {"role": "user", "content": json.dumps(context)},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "PrinterComparison",
                            "strict": True,
                            "schema": Advice.model_json_schema(),
                        },
                    },
                    reasoning_effort="low",
                    max_completion_tokens=4096,
                ),
            )
        if response.status_code >= 400:
            raise ValueError()
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
            raise ValueError()
        advice = Advice.model_validate_json(choice["message"]["content"])
        validate_advice(advice, batch)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise integrations.IntegrationError(
            "Meta comparison unavailable or failed validation. No quote or reservation changed."
        ) from None
    return dict(model=model, source="meta_model_api", **advice.model_dump())


def validate_advice(advice, batch):
    options = {o["option_id"]: o for o in batch["options"]}
    ids = [a.option_id for a in advice.assessments]
    if len(ids) != len(set(ids)) or set(ids) != set(options):
        raise ValueError("Coverage")
    for a in advice.assessments:
        if len(a.reason_codes) != len(set(a.reason_codes)) or not set(
            a.reason_codes
        ) <= set(options[a.option_id]["valid_reason_codes"]):
            raise ValueError("Unsupported reason")
    eligible = {
        k
        for k, o in options.items()
        if o["on_time"] and not o["support_review_required"]
    }
    if (eligible and advice.recommended_option_id not in eligible) or (
        not eligible and advice.recommended_option_id is not None
    ):
        raise ValueError("Recommendation")


def register(app):
    # main is fully initialized when routes are registered; tests may reload it.
    from backend import main as m

    @app.post("/api/jobs/{job_id}/comparisons", status_code=202)
    def compare(job_id: str, body: CompareRequest, background: BackgroundTasks):
        ids = list(dict.fromkeys(body.profile_ids))
        if any(not 0 <= v <= 100 for v in body.support_percent_by_profile.values()):
            m.fail("Invalid support percentage", 422)
        allowed = {
            p["id"]
            for p in integrations.profile_definitions()
            if p.get("printer", {}).get("id")
            in ("bambu-a1", "bambu-a1mini", "bambu-x2d")
        }
        if not set(ids) <= allowed:
            m.fail("Select imported A1, A1 mini or X2D profiles", 422)
        with m.transaction() as c:
            job = m.get(c, job_id, "job")
            if (
                job["status"]
                not in ("draft", "ready_for_quote", "quote_ready", "recovery_required")
                or not job.get("file")
                or not job.get("units")
            ):
                m.fail(
                    "Upload a mesh and confirm units; use pre-start recovery for committed jobs"
                )
            if (
                job.get("reservation_id")
                and m.parse(m.get(c, job["reservation_id"], "reservation")["start"])
                <= m.now()
            ):
                m.fail("In-progress recovery requires manual review")
            if any(
                t["status"] in ("queued", "running") for t in m.rows(c, "task")
            ) or any(
                b["status"] in ("queued", "running") for b in m.rows(c, "comparison")
            ):
                m.fail("Wait for active slicing/comparison to finish")
            dims = [
                v * {"mm": 1, "cm": 10, "in": 25.4}[job["units"]]
                for v in job["file"]["dimensions_native"]
            ]
            hashes = {}
            for pid in ids:
                try:
                    p, _, fp = integrations.load_profile(pid)
                except integrations.IntegrationError as exc:
                    m.fail(str(exc), 422)
                if not all(a <= b for a, b in zip(dims, p["bed_mm"])):
                    m.fail(
                        "Part exceeds a selected profile build volume; deselect it", 422
                    )
                if not any(
                    p["active"]
                    and p["profile"] == pid
                    and p["material"] == job["material"]
                    for p in m.rows(c, "printer")
                ):
                    m.fail("Selected profile has no compatible active printer", 422)
                hashes[pid] = fp
            batch = dict(
                id=m.uid(),
                job_id=job_id,
                status="queued",
                profile_ids=ids,
                profile_hashes=hashes,
                support_percent_by_profile=body.support_percent_by_profile,
                created_at=m.stamp(),
                expires_at=(m.now() + timedelta(minutes=15)).isoformat(),
                snapshot_hash=fingerprint(m, c, job, ids),
                options=[],
                excluded=[],
                approval_required=True,
            )
            m.put(c, "comparison", batch)
            m.audit(c, job_id, "comparison_requested", {"comparison_id": batch["id"]})
        background.add_task(worker, m, batch["id"])
        return batch

    @app.get("/api/jobs/{job_id}/comparisons")
    def latest(job_id: str):
        with m.engine.connect() as c:
            batches = [b for b in m.rows(c, "comparison") if b["job_id"] == job_id]
            if not batches:
                return {"status": "not_requested"}
            b = max(batches, key=lambda item: item["created_at"])
            if b["status"] == "ready":
                try:
                    verify(m, c, b)
                except Exception:
                    return {
                        "id": b["id"],
                        "status": "stale",
                        "error": "Inputs or capacity changed; compare again.",
                    }
            return b

    @app.post("/api/comparisons/{comparison_id}/explanation")
    def explain(comparison_id: str, body: ExplainRequest):
        with m.transaction() as c:
            b = m.get(c, comparison_id, "comparison")
            verify(m, c, b)
            if b.get("advice"):
                return b["advice"]
        try:
            advice = ask_meta(b)
        except integrations.IntegrationError as exc:
            m.fail(str(exc), 503)
        with m.transaction() as c:
            current = m.get(c, comparison_id, "comparison")
            verify(m, c, current)
            for a in advice["assessments"]:
                a["reasons"] = [REASONS[code] for code in a["reason_codes"]]
            current["advice"] = advice
            m.put(c, "comparison", current)
            m.audit(
                c,
                current["job_id"],
                "comparison_explained",
                {"comparison_id": comparison_id, "model": advice["model"]},
            )
        return advice

    @app.post("/api/comparisons/{comparison_id}/approve")
    def commit(comparison_id: str, body: CommitRequest):
        with m.transaction() as c:
            b = m.get(c, comparison_id, "comparison")
            for previous in m.rows(c, "comparison_approval"):
                if previous["idempotency_key"] == body.idempotency_key:
                    if (
                        previous["comparison_id"] != comparison_id
                        or previous["option_id"] != body.option_id
                        or previous["total_cents"] != body.total_cents
                        or previous["currency"] != body.currency
                    ):
                        m.fail("Idempotency key belongs to a different approval")
                    return previous["result"]
            job = verify(m, c, b)
            option = next(
                (o for o in b["options"] if o["option_id"] == body.option_id), None
            )
            if not option or not option["on_time"] or option["support_review_required"]:
                m.fail("Select an on-time option with reviewed supports")
            if (
                option["total_cents"] != body.total_cents
                or option["currency"] != body.currency
            ):
                m.fail(
                    "Explicit approval must match the displayed quote total and currency"
                )
            old = (
                m.get(c, job["reservation_id"], "reservation")
                if job.get("reservation_id")
                else None
            )
            job["latest_quote_id"] = option["quote_id"]
            if not old:
                job["status"] = "quote_ready"
            m.put(c, "job", job)
            p = dict(
                id=m.uid(),
                job_id=job["id"],
                job_version=job["version"],
                quote_id=option["quote_id"],
                kind="recovery" if old else "schedule",
                status="proposed",
                choice=option,
                old_reservation=old,
                expires_at=b["expires_at"],
            )
            m.put(c, "proposal", p)
            result = m.approve_in_transaction(
                c, p["id"], m.Approve(idempotency_key=body.idempotency_key)
            )
            b["status"] = "approved"
            b["approved_option_id"] = option["option_id"]
            m.put(c, "comparison", b)
            m.put(
                c,
                "comparison_approval",
                dict(
                    id=m.uid(),
                    comparison_id=comparison_id,
                    option_id=body.option_id,
                    total_cents=body.total_cents,
                    currency=body.currency,
                    idempotency_key=body.idempotency_key,
                    result=result,
                ),
            )
            m.audit(
                c,
                job["id"],
                "comparison_approved",
                {"comparison_id": comparison_id, "quote_id": option["quote_id"]},
            )
            return result
