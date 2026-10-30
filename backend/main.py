"""Local operator demo. All workflow mutations serialize at the shop transaction boundary."""

import hashlib
import json
import math
import os
import uuid
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column,
    JSON,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    text,
)
from backend import integrations
from backend import recovery as recovery_ai
from backend.pricing import RateCard, calculate

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DATA.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    os.getenv("DATABASE_URL", "sqlite:///" + (DATA / "shop.db").as_posix()),
    connect_args={"check_same_thread": False, "timeout": 30}
    if not os.getenv("DATABASE_URL", "").startswith("postgres")
    else {},
)
meta = MetaData()
records = Table(
    "records",
    meta,
    Column("id", String, primary_key=True),
    Column("kind", String, index=True, nullable=False),
    Column("payload", JSON, nullable=False),
)
meta.create_all(engine)


@asynccontextmanager
async def lifespan(app):
    # One API process owns the prototype background tasks. Do not run multiple workers.
    with transaction() as c:
        for task in rows(c, "task"):
            if task["status"] in ("queued", "running"):
                task.update(
                    status="failed",
                    error="Server restarted before slicing completed. Submit a new task.",
                    finished_at=stamp(),
                )
                put(c, "task", task)
        for batch in rows(c, "comparison"):
            if batch["status"] in ("queued", "running"):
                batch.update(
                    status="failed",
                    error="Server restarted during comparison. Compare again.",
                )
                put(c, "comparison", batch)
    yield


app = FastAPI(title="Print3DFlow Manufacturing MVP", version="0.2.0", lifespan=lifespan)


def now():
    return datetime.now(timezone.utc)


def stamp():
    return now().isoformat()


def uid():
    return uuid.uuid4().hex


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fail(message, status=409):
    raise HTTPException(status, message)


@contextmanager
def transaction():
    with engine.connect() as conn:
        try:
            if engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(731042)"))
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def rows(c, kind):
    return list(
        c.execute(select(records.c.payload).where(records.c.kind == kind)).scalars()
    )


def get(c, key, kind=None):
    row = c.execute(select(records).where(records.c.id == key)).mappings().first()
    if not row or (kind and row["kind"] != kind):
        fail("Record not found", 404)
    return row["payload"]


def put(c, kind, obj):
    exists = c.execute(select(records.c.id).where(records.c.id == obj["id"])).first()
    if exists:
        c.execute(records.update().where(records.c.id == obj["id"]).values(payload=obj))
    else:
        c.execute(records.insert().values(id=obj["id"], kind=kind, payload=obj))
    return obj


def audit(c, job, event, details):
    put(
        c,
        "audit",
        dict(
            id=uid(),
            job_id=job,
            event=event,
            details=details,
            actor="local-demo-operator",
            created_at=stamp(),
        ),
    )


def snapshot(c):
    return {
        k: rows(c, kind)
        for k, kind in [
            ("jobs", "job"),
            ("printers", "printer"),
            ("quotes", "quote"),
            ("proposals", "proposal"),
            ("reservations", "reservation"),
            ("outages", "outage"),
            ("audit", "audit"),
            ("tasks", "task"),
        ]
    }


def seed():
    with transaction() as c:
        if rows(c, "printer"):
            return
        for key, name in [("printer-a", "Atlas A"), ("printer-b", "Atlas B")]:
            put(
                c,
                "printer",
                dict(
                    id=key,
                    name=name,
                    material="PLA",
                    bed_mm=[220, 220, 250],
                    profile="demo-pla-0.2-v1",
                    active=True,
                ),
            )


seed()


def seed_registered_printers():
    """Register confirmed local profile capacity; no telemetry or printer commands."""
    with transaction() as c:
        existing = {p["id"] for p in rows(c, "printer")}
        for definition in integrations.profile_definitions():
            printer = definition.get("printer")
            if not printer or printer["id"] in existing:
                continue
            try:
                integrations.load_profile(definition["id"])
            except integrations.IntegrationError:
                continue
            put(
                c,
                "printer",
                dict(
                    id=printer["id"],
                    name=printer["name"],
                    material="PLA",
                    bed_mm=definition["bed_mm"],
                    profile=definition["id"],
                    active=True,
                    telemetry_connected=False,
                    source="operator_provided_project",
                ),
            )


seed_registered_printers()


class Intake(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    request: str = Field(default="", max_length=4000)
    quantity: int = Field(default=1, ge=1, le=100)
    material: Literal["PLA", "PETG", "ABS", "ASA", "TPU"] = "PLA"
    finish: Literal["as-printed", "sanding", "painting", "other"] = "as-printed"
    color: str | None = Field(default=None, max_length=80)
    units: Literal["mm", "cm", "in"] | None = None
    deadline: datetime
    intake_draft_id: str | None = None
    ai_review_confirmed: bool = False
    material_override_confirmed: bool = False
    model_upload_id: str | None = None

    @field_validator("deadline")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("Deadline must include a time zone")
        if v <= now():
            raise ValueError("Deadline must be in the future")
        return v


class Estimates(BaseModel):
    grams_per_part: float = Field(gt=0, le=10000)
    hours_per_part: float = Field(gt=0, le=240)
    orientation: Literal["uploaded"] = "uploaded"
    infill_percent: int = Field(default=20, ge=0, le=100)
    layer_height_mm: float = Field(default=0.2, ge=0.08, le=0.4)
    walls: int = Field(default=3, ge=1, le=10)
    supports: bool = False
    confirmed: Literal[True]
    support_percent: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    apply_support_surcharge: bool = False


class Approve(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)


class Outage(BaseModel):
    printer_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    event_key: str = Field(min_length=8, max_length=100)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("Time zone required")
        return v


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "local-operator-demo",
        "meta_configured": integrations.meta_configured(),
        "slicer_configured": any(
            p["available"] for p in integrations.public_profiles()
        ),
        "database": engine.dialect.name,
    }


@app.get("/api/filaments")
def filament_catalog():
    from backend.filaments import catalog

    return {"materials": catalog()}


@app.get("/api/integrations")
def integration_status():
    return {
        "meta": {
            "configured": integrations.meta_configured(),
            "model": integrations.meta_provider.config()[2],
            "provider": integrations.meta_provider.config()[0],
            "live_verified": False,
        },
        "slicer": {
            "engine": "Bambu Studio",
            "profiles": integrations.public_profiles(),
        },
        "shop_timezone": os.getenv("SHOP_TIMEZONE", "America/New_York"),
    }


class DraftRequest(BaseModel):
    requested_finish: Literal["as-printed", "sanding", "painting", "other"] | None = None
    requested_material: Literal["PLA", "PETG", "ABS", "ASA", "TPU"] | None = None
    request: str = Field(min_length=5, max_length=4000)
    model_upload_id: str | None = None


@app.post("/api/intake/drafts", status_code=201)
def intake_draft(body: DraftRequest):
    context = None
    if body.model_upload_id:
        with engine.connect() as c:
            staged = get(c, body.model_upload_id, "model_upload")
            if staged.get("repair_review_required"):
                fail("Approve the repaired geometry before Meta intake", 422)
            if staged["consumed_by"] or parse(staged["expires_at"]) <= now():
                fail("Model upload expired or already used; upload again")
            f = staged["file"]
            context = dict(
                format=f["source_format"],
                dimensions_native=f["dimensions_native"],
                embedded_units=f.get("embedded_units"),
                geometry_units="mm" if f["source_format"] == "3mf" else None,
            )
            if f["source_format"] == "3mf":
                from backend.color_inspection import infer_material, infer_colors

                context["material_inference"] = infer_material(
                    f.get("color_info") or {}
                )
                context["color_inference"] = infer_colors(f.get("color_info") or {})
    try:
        result = integrations.extract_intake(
            body.request,
            file_context=context,
            requested_material=body.requested_material,
            requested_finish=body.requested_finish,
        )
    except integrations.IntegrationError as exc:
        fail(str(exc), 503)
    result.update(
        id=uid(),
        request=body.request,
        created_at=stamp(),
        model_upload_id=body.model_upload_id,
        file_context=context,
    )
    with transaction() as c:
        put(c, "intake_draft", result)
    return result


@app.get("/api/state")
def state():
    with engine.connect() as c:
        return snapshot(c)


@app.post("/api/jobs", status_code=201)
def create_job(body: Intake):
    with transaction() as c:
        if not body.model_upload_id:
            fail("Submit a valid STL or 3MF file before creating a print job", 422)
        staged = get(c, body.model_upload_id, "model_upload")
        if staged.get("repair_review_required"):
            fail("Review and explicitly approve the repaired model before use", 422)
        if staged["consumed_by"] or parse(staged["expires_at"]) <= now():
            fail("Model upload already used or expired; upload the file again")
        model_path = DATA / (staged["file"]["sha256"] + ".stl")
        if (
            not model_path.is_file()
            or hashlib.sha256(model_path.read_bytes()).hexdigest()
            != staged["file"]["sha256"]
        ):
            fail("Validated model is unavailable; upload the file again")
        if body.intake_draft_id:
            draft = get(c, body.intake_draft_id, "intake_draft")
            if (
                draft.get("model_upload_id")
                and draft["model_upload_id"] != body.model_upload_id
            ):
                fail("Model changed after Meta review; extract a fresh draft", 422)
            if not body.ai_review_confirmed:
                fail("Review and confirm the AI draft before creating a job", 422)
            if body.request != draft["request"]:
                fail("AI source request changed; regenerate or use manual intake", 422)
            if (
                draft["draft"]["material"]
                and draft["draft"]["material"].upper() != body.material
                and not body.material_override_confirmed
            ):
                fail(
                    "Requested filament differs from the reviewed Meta draft. Revise the request and extract again.",
                    422,
                )
        if body.intake_draft_id and body.finish == "as-printed":
            extracted_finish = (draft["draft"].get("finish") or "").strip().lower()
            if extracted_finish and extracted_finish not in ("as-printed", "as printed", "none", "no finishing"):
                fail("Finish conflicts with the Meta draft. Resolve the request and extract again before selecting as-printed.", 422)
        job = dict(
            id=uid(),
            **body.model_dump(mode="json"),
            status="needs_clarification"
            if body.units is None and staged["file"]["source_format"] != "3mf"
            else "ready_for_quote",
            version=1,
            requirements_version=1,
            created_at=stamp(),
            file=staged["file"],
        )
        if staged["file"]["source_format"] == "3mf":
            job["units"] = "mm"
        staged["consumed_by"] = job["id"]
        if job["material"] != "PLA":
            job["status"] = "awaiting_material_profile"
        if job["finish"] != "as-printed":
            job["status"] = "awaiting_finish_review"
        put(c, "model_upload", staged)
        put(c, "job", job)
        audit(c, job["id"], "mesh_validated", job["file"])
        audit(
            c,
            job["id"],
            "job_created",
            {
                "mode": "meta_draft_operator_reviewed"
                if body.intake_draft_id
                else "manual_structured_intake",
                "intake_draft_id": body.intake_draft_id,
            },
        )
        return job


@app.patch("/api/jobs/{job_id}/requirements")
def requirements(job_id: str, body: Intake):
    with transaction() as c:
        job = get(c, job_id, "job")
        if job["status"] in ("scheduled", "recovery_required", "completed"):
            fail("Scheduled jobs cannot change manufacturing requirements")
        updates = body.model_dump(mode="json")
        if "finish" not in body.model_fields_set:
            updates.pop("finish", None)
        job.update(updates)
        job["version"] += 1
        job["requirements_version"] += 1
        job["status"] = "needs_clarification" if body.units is None else "draft"
        put(c, "job", job)
        audit(c, job_id, "requirements_updated", {"version": job["version"]})
        return job


async def validate_model_upload(file):
    from backend.model_processing import process_upload

    metadata, normalized, _ = await process_upload(file, DATA)
    return metadata, normalized


@app.post("/api/model-uploads", status_code=201)
async def stage_model(file: UploadFile = File(...)):
    metadata, normalized = await validate_model_upload(file)
    with transaction() as c:
        (DATA / (metadata["sha256"] + ".stl")).write_bytes(normalized)
        staged = dict(
            id=uid(),
            file=metadata,
            expires_at=(now() + timedelta(hours=1)).isoformat(),
            consumed_by=None,
        )
        put(c, "model_upload", staged)
    return {"id": staged["id"], "file": metadata, "expires_at": staged["expires_at"]}


@app.post("/api/jobs/{job_id}/file")
async def upload(job_id: str, file: UploadFile = File(...)):
    metadata, normalized = await validate_model_upload(file)
    with transaction() as c:
        job = get(c, job_id, "job")
        if job["status"] in ("scheduled", "recovery_required", "completed"):
            fail("Cannot replace a scheduled mesh")
        job["file"] = metadata
        if metadata["source_format"] == "3mf":
            job["units"] = "mm"
        job["version"] += 1
        job["requirements_version"] += 1
        job["status"] = "ready_for_quote" if job["units"] else "needs_clarification"
        (DATA / (metadata["sha256"] + ".stl")).write_bytes(normalized)
        put(c, "job", job)
        audit(c, job_id, "mesh_validated", job["file"])
        return job


def cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def current_rates(c):
    cards = rows(c, "rate_card")
    if not cards:
        return put(
            c,
            "rate_card",
            dict(
                id="demo-usd-v1",
                created_at=stamp(),
                mode="demo",
                rates=RateCard().model_dump(mode="json"),
            ),
        )
    return max(cards, key=lambda r: r["created_at"])


@app.get("/api/pricing")
def pricing():
    with transaction() as c:
        return current_rates(c)


@app.post("/api/pricing", status_code=201)
def save_pricing(body: RateCard):
    with transaction() as c:
        card = put(
            c,
            "rate_card",
            dict(
                id="shop-" + uid(),
                created_at=stamp(),
                mode="shop",
                rates=body.model_dump(mode="json"),
            ),
        )
        audit(c, None, "shop_rates_saved", {"rate_card": card["id"]})
        return card


class StudioComparison(BaseModel):
    studio_grams: float = Field(gt=0, le=10000, allow_inf_nan=False)
    studio_minutes: float = Field(gt=0, le=14400, allow_inf_nan=False)
    same_part_and_settings_confirmed: Literal[True]


@app.post("/api/quotes/{quote_id}/studio-comparisons", status_code=201)
def compare_studio(quote_id: str, body: StudioComparison):
    with transaction() as c:
        q = get(c, quote_id, "quote")
        if q["source"] != "bambu_studio":
            fail("Comparison requires a slicer-backed quote", 422)
        job = get(c, q["job_id"], "job")
        if q["job_version"] != job["requirements_version"]:
            fail("Requirements changed; generate a new slice before comparing")
        _, _, fingerprint = integrations.load_profile(q["profile"])
        if fingerprint != q["slicer"]["profile_sha256"]:
            fail("Profile changed; generate a new slice before comparing")
        baseline = q["slicer"]
        grams = float(baseline["grams_per_part"])
        minutes = (
            float(baseline.get("seconds_per_part", baseline["hours_per_part"] * 3600))
            / 60
        )
        delta_g = (body.studio_grams / grams - 1) * 100
        delta_t = (body.studio_minutes / minutes - 1) * 100
        result = dict(
            id=uid(),
            quote_id=quote_id,
            job_id=q["job_id"],
            profile_sha256=fingerprint,
            mesh_sha256=q.get("mesh_sha256", job["file"]["sha256"]),
            created_at=stamp(),
            quantity_basis="one part",
            cli_grams=grams,
            cli_minutes=minutes,
            studio_grams=body.studio_grams,
            studio_minutes=body.studio_minutes,
            mass_difference_percent=delta_g,
            time_difference_percent=delta_t,
            within_tolerance=abs(delta_g) <= 2 and abs(delta_t) <= 5,
            tolerance={"mass_percent": 2, "time_percent": 5},
            kind="bambu_estimate_agreement",
            physical_print_calibrated=False,
        )
        put(c, "studio_comparison", result)
        audit(
            c,
            q["job_id"],
            "bambu_estimates_compared",
            {
                "comparison_id": result["id"],
                "within_tolerance": result["within_tolerance"],
            },
        )
        return result


@app.get("/api/quotes/{quote_id}/studio-comparisons")
def studio_comparisons(quote_id: str):
    with engine.connect() as c:
        get(c, quote_id, "quote")
        return [r for r in rows(c, "studio_comparison") if r["quote_id"] == quote_id]


@app.get("/api/quotes/{quote_id}/comparison-project")
def comparison_project(quote_id: str):
    with engine.connect() as c:
        q = get(c, quote_id, "quote")
        if q["source"] != "bambu_studio" or not q.get("slicer", {}).get("from_project"):
            fail(
                "A comparison project is only available for native project-backed quotes",
                404,
            )
        task = get(c, q["slicer"]["task_id"], "task")
        if task["status"] != "succeeded" or task.get("quote_id") != quote_id:
            fail("No matching successful slice is available", 404)
        path = DATA / "slices" / task["id"] / "quote.3mf"
        if not path.is_file():
            fail("Comparison project is unavailable", 404)
        return FileResponse(
            path,
            media_type="application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
            filename="X2D-quote-comparison.3mf",
        )


def build_quote(c, job, body: Estimates, provenance=None):
    from backend.color_inspection import require_single_filament

    if not (provenance or {}).get("verified_multicolor"):
        require_single_filament(job)
    if job["material"] != "PLA":
        fail(
            "Configure verified matching filament profiles and material rates before quoting this request",
            422,
        )
    if job["status"] in ("scheduled", "recovery_required", "completed"):
        fail("Job is already committed")
    if not job["file"] or not job["units"]:
        fail("Upload a valid model and confirm units before quoting", 422)
    scale = {"mm": 1, "cm": 10, "in": 25.4}[job["units"]]
    dims = [round(x * scale, 4) for x in job["file"]["dimensions_native"]]
    if not any(
        all(a <= b for a, b in zip(dims, p["bed_mm"])) for p in rows(c, "printer")
    ):
        fail("Part does not fit a supported printer in the uploaded orientation", 422)
    job_id = job["id"]
    qty = job["quantity"]
    grams = Decimal(str(body.grams_per_part)) * qty
    hours = Decimal(str(body.hours_per_part)) * qty
    card = current_rates(c)
    rates = RateCard.model_validate(card["rates"])
    if (provenance or {}).get("verified_multicolor"):
        rates = rates.model_copy(update={"waste_percent": Decimal(0)})
    try:
        price = calculate(
            grams, hours, rates, body.support_percent, body.apply_support_surcharge
        )
    except ValueError as exc:
        fail(str(exc), 422)
    result = dict(
        id=uid(),
        job_id=job_id,
        job_version=job["requirements_version"],
        created_at=stamp(),
        expires_at=(now() + timedelta(hours=24)).isoformat(),
        currency=rates.currency,
        source="operator_entered_estimate",
        profile="demo-pla-0.2-v1",
        rate_card=card["id"],
        rate_snapshot=card,
        pricing_mode=card["mode"],
        mesh_sha256=job["file"]["sha256"],
        reservation_buffer_minutes=rates.reservation_buffer_minutes,
        estimates=body.model_dump(),
        dimensions_mm=dims,
        quantity_policy="sequential parts; no batch packing",
        grams=float(grams),
        hours=float(hours),
        duration_minutes=math.ceil(Decimal(price["billable_hours"]) * 60)
        + rates.reservation_buffer_minutes,
        billable_hours=price["billable_hours"],
        support_surcharge_applied=price["support_surcharge_applied"],
        support_review_required=body.supports
        and rates.support_surcharge_per_kg > 0
        and body.support_percent is None,
        items=price["items"],
        total_cents=price["total_cents"],
        assumptions=[
            "Preliminary operator-entered estimates; not slicer-backed",
            f"{rates.reservation_buffer_minutes} minutes setup/cooldown included in reservation; not billed as print time",
            "No tax, shipping, or finishing",
            "Uploaded orientation; settings confirmed by operator",
        ],
        input_hash=hashlib.sha256(
            json.dumps(
                {"job": job, "estimate": body.model_dump()}, sort_keys=True
            ).encode()
        ).hexdigest(),
    )
    if provenance:
        result.update(
            source="bambu_studio", slicer=provenance, profile=provenance["profile_id"]
        )
        result["assumptions"][0] = (
            "Bambu Studio slice estimate; actual print accuracy requires shop calibration"
        )
    put(c, "quote", result)
    job["status"] = "quote_ready"
    job["latest_quote_id"] = result["id"]
    put(c, "job", job)
    audit(
        c,
        job_id,
        "quote_created",
        {"quote_id": result["id"], "source": result["source"]},
    )
    return result


@app.post("/api/jobs/{job_id}/quotes", status_code=201)
def quote(job_id: str, body: Estimates):
    with transaction() as c:
        return build_quote(c, get(c, job_id, "job"), body)


def valid_quote(c, job):
    from backend.color_inspection import require_single_filament

    if not job.get("latest_quote_id"):
        fail("Create a quote first")
    q = get(c, job["latest_quote_id"], "quote")
    if q.get("source") == "bambu_multicolor":
        from backend.multicolor import validate_quote
        validate_quote(__import__(__name__, fromlist=['']), c, job, q)
    else:
        require_single_filament(job)
    if q.get("support_review_required"):
        fail(
            "Review the support percentage and optional surcharge, then generate a new quote before reserving."
        )
    if (
        q["job_version"] != job["requirements_version"]
        or parse(q["expires_at"]) <= now()
    ):
        fail("Quote is stale or expired; requote required")
    if q["source"] == "bambu_studio":
        try:
            _, _, fingerprint = integrations.load_profile(q["profile"])
        except integrations.IntegrationError as exc:
            fail(str(exc), 409)
        if fingerprint != q["slicer"]["profile_sha256"]:
            fail("Slicer profile changed; slice and requote before approval")
    return q


class SliceRequest(BaseModel):
    profile_id: str = Field(default="demo-pla-0.2-v1", min_length=1, max_length=100)
    confirmed: Literal[True]
    idempotency_key: str = Field(min_length=8, max_length=100)
    support_percent: float | None = Field(
        default=None, ge=0, le=100, allow_inf_nan=False
    )
    apply_support_surcharge: bool = False


def slice_worker(task_id: str):
    try:
        with transaction() as c:
            task = get(c, task_id, "task")
            task.update(status="running", started_at=stamp())
            put(c, "task", task)
            original = get(c, task["job_id"], "job")
        result = integrations.run_bambu_slice(
            DATA / (original["file"]["sha256"] + ".stl"),
            original["units"],
            task["profile_id"],
            DATA / "slices" / task_id,
        )
        result["task_id"] = task_id
        with transaction() as c:
            current = get(c, task["job_id"], "job")
            if current["version"] != task["job_version"] or current.get(
                "latest_quote_id"
            ) != task.get("previous_quote_id"):
                raise integrations.IntegrationError(
                    "Job or quote changed while slicing. The result was not applied; submit a fresh task."
                )
            _, _, fingerprint = integrations.load_profile(task["profile_id"])
            if (
                fingerprint != result["profile_sha256"]
                or result["profile_sha256"] != task["profile_sha256"]
            ):
                raise integrations.IntegrationError(
                    "Profile changed while slicing; slice again before quoting."
                )
            settings = result["settings"]
            inputs = Estimates(
                grams_per_part=result["grams_per_part"],
                hours_per_part=result["hours_per_part"],
                confirmed=True,
                layer_height_mm=settings["layer_height_mm"],
                infill_percent=settings["infill_percent"],
                walls=settings["walls"],
                supports=settings["supports"],
                support_percent=task.get("support_percent"),
                apply_support_surcharge=task.get("apply_support_surcharge", False),
            )
            q = build_quote(c, current, inputs, result)
            task = get(c, task_id, "task")
            task.update(status="succeeded", quote_id=q["id"], finished_at=stamp())
            put(c, "task", task)
    except Exception as exc:
        # Persist a safe, reviewable failure; never silently substitute manual estimates.
        message = (
            str(exc)
            if isinstance(exc, integrations.IntegrationError)
            else "Slicing could not complete. Review the local task artifacts and supported profile settings."
        )
        with transaction() as c:
            task = get(c, task_id, "task")
            task.update(status="failed", error=message, finished_at=stamp())
            put(c, "task", task)
            audit(
                c,
                task["job_id"],
                "slicing_failed",
                {"task_id": task_id, "error": message},
            )


@app.post("/api/jobs/{job_id}/slice-quotes", status_code=202)
def slice_quote(job_id: str, body: SliceRequest, background: BackgroundTasks):
    from backend.color_inspection import require_single_filament

    with transaction() as c:
        require_single_filament(get(c, job_id, "job"))
    try:
        profile, _, fingerprint = integrations.load_profile(body.profile_id)
    except integrations.IntegrationError as exc:
        fail(str(exc), 422)
    if not integrations.bambu_executable().is_file():
        fail("Bambu Studio executable is not configured", 503)
    with transaction() as c:
        job = get(c, job_id, "job")
        if job["material"] != "PLA":
            fail(
                "Material profile and rates are not configured; PLA settings cannot be substituted",
                422,
            )
        from backend.color_inspection import require_single_filament

        require_single_filament(job)
        for existing in rows(c, "task"):
            if existing["idempotency_key"] == body.idempotency_key:
                if (
                    existing["job_id"] != job_id
                    or existing["profile_id"] != body.profile_id
                ):
                    fail("Idempotency key belongs to another task")
                return existing
        if job["status"] in ("scheduled", "recovery_required", "completed"):
            fail("Scheduled jobs cannot be requoted")
        if not job["file"] or not job["units"]:
            fail("Upload a model and confirm units before slicing", 422)
        dimensions = [
            v * {"mm": 1, "cm": 10, "in": 25.4}[job["units"]]
            for v in job["file"]["dimensions_native"]
        ]
        if not all(a <= b for a, b in zip(dimensions, profile["bed_mm"])):
            fail(
                "Mesh exceeds the selected profile envelope in the uploaded orientation",
                422,
            )
        if not any(
            p["active"]
            and p["profile"] == body.profile_id
            and all(a <= b for a, b in zip(dimensions, p["bed_mm"]))
            for p in rows(c, "printer")
        ):
            fail("No active printer is bound to this profile and part size", 422)
        tasks = rows(c, "task")
        if any(
            t["job_id"] == job_id and t["status"] in ("queued", "running")
            for t in tasks
        ):
            fail("A slice task is already active for this job")
        if sum(t["status"] in ("queued", "running") for t in tasks) >= 2:
            fail(
                "Two slicing tasks are already active. Retry after one completes.", 429
            )
        task = dict(
            id=uid(),
            kind="slice_quote",
            job_id=job_id,
            job_version=job["version"],
            previous_quote_id=job.get("latest_quote_id"),
            profile_id=body.profile_id,
            profile_sha256=fingerprint,
            idempotency_key=body.idempotency_key,
            status="queued",
            created_at=stamp(),
            support_percent=body.support_percent,
            apply_support_surcharge=body.apply_support_surcharge,
        )
        put(c, "task", task)
        audit(
            c,
            job_id,
            "slicing_queued",
            {"task_id": task["id"], "profile_id": body.profile_id},
        )
    background.add_task(slice_worker, task["id"])
    return task


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str):
    with engine.connect() as c:
        return get(c, task_id, "task")


@app.get("/api/tasks/{task_id}/report")
def slice_report(task_id: str):
    with engine.connect() as c:
        task = get(c, task_id, "task")
        if task["status"] != "succeeded":
            fail("No successful slice report is available", 404)
    return FileResponse(
        DATA / "slices" / task["id"] / "result.json",
        media_type="application/json",
        filename="bambu-slice-report.json",
    )


def overlaps(a, b, c, d):
    return a < d and c < b


def slots(c, job, q, ignore=None):
    earliest = (now() + timedelta(minutes=5)).replace(second=0, microsecond=0)
    choices = []
    for printer in rows(c, "printer"):
        if (
            not printer["active"]
            or printer["material"] != job["material"]
            or printer["profile"] != q["profile"]
        ):
            continue
        if not all(a <= b for a, b in zip(q["dimensions_mm"], printer["bed_mm"])):
            continue
        blocks = [
            (parse(r["start"]), parse(r["end"]))
            for r in rows(c, "reservation")
            if r["printer_id"] == printer["id"] and r["active"] and r["id"] != ignore
        ]
        blocks += [
            (parse(o["starts_at"]), parse(o["ends_at"]))
            for o in rows(c, "outage")
            if o["printer_id"] == printer["id"]
        ]
        start = earliest
        duration = timedelta(minutes=q["duration_minutes"])
        for begin, end in sorted(blocks):
            if start + duration <= begin:
                break
            if start < end:
                start = end
        choices.append(
            dict(
                printer_id=printer["id"],
                printer_name=printer["name"],
                start=start.isoformat(),
                end=(start + duration).isoformat(),
                on_time=start + duration <= parse(job["deadline"]),
            )
        )
    return sorted(choices, key=lambda x: (not x["on_time"], x["end"], x["printer_id"]))


def proposal(c, job, recovery=False):
    q = valid_quote(c, job)
    old = get(c, job["reservation_id"], "reservation") if recovery else None
    if old and parse(old["start"]) <= now():
        fail(
            "In-progress jobs require manual recovery; this demo supports pre-start outages only"
        )
    choices = slots(c, job, q, old["id"] if old else None)
    if not choices:
        fail("No compatible printer; manual review required", 422)
    choices = [
        dict(option_id=f"option-{i + 1}", **option) for i, option in enumerate(choices)
    ]
    chosen = choices[0]
    result = dict(
        id=uid(),
        job_id=job["id"],
        job_version=job["version"],
        quote_id=q["id"],
        kind="recovery" if recovery else "schedule",
        created_at=stamp(),
        expires_at=(now() + timedelta(minutes=15)).isoformat(),
        choice=chosen,
        alternatives=choices[1:],
        old_reservation=old,
        status="proposed",
        message_draft=f"Your job {job['title']} is proposed for {chosen['printer_name']}, completing {chosen['end']}. "
        + (
            "Your requested deadline remains feasible."
            if chosen["on_time"]
            else "This exceeds the requested deadline; please contact the customer before committing."
        ),
    )
    put(c, "proposal", result)
    audit(
        c,
        job["id"],
        "recovery_proposed" if recovery else "schedule_proposed",
        {"proposal_id": result["id"], "on_time": chosen["on_time"]},
    )
    return result


@app.post("/api/jobs/{job_id}/proposals", status_code=201)
def propose(job_id: str):
    with transaction() as c:
        job = get(c, job_id, "job")
        if job["status"] != "quote_ready":
            fail("Job must have an uncommitted quote")
        return proposal(c, job)


@app.post("/api/jobs/{job_id}/recovery", status_code=201)
def recover(job_id: str):
    with transaction() as c:
        job = get(c, job_id, "job")
        if job["status"] != "recovery_required":
            fail("Job does not need recovery")
        return proposal(c, job, True)


def verified_recovery(c, p):
    job = get(c, p["job_id"], "job")
    if (
        p["kind"] != "recovery"
        or p["status"] != "proposed"
        or job["status"] != "recovery_required"
        or p["job_version"] != job["version"]
        or parse(p["expires_at"]) <= now()
    ):
        fail("Recovery proposal is stale; generate a new proposal.")
    q = valid_quote(c, job)
    if q["id"] != p["quote_id"] or not all(
        "option_id" in o for o in [p["choice"], *p["alternatives"]]
    ):
        fail("Recovery inputs changed; generate a new proposal.")
    old = get(c, p["old_reservation"]["id"], "reservation")
    try:
        return recovery_ai.snapshot(
            p,
            job,
            q,
            old,
            rows(c, "printer"),
            rows(c, "reservation"),
            rows(c, "outage"),
            now(),
        )
    except ValueError as exc:
        fail(str(exc))


@app.post("/api/proposals/{proposal_id}/explanation")
def explain_recovery(proposal_id: str):
    with transaction() as c:
        p = get(c, proposal_id, "proposal")
        verified = verified_recovery(c, p)
        if p.get("explanation_id"):
            cached = get(c, p["explanation_id"], "recovery_explanation")
            if cached["snapshot_hash"] == verified["snapshot_hash"]:
                return recovery_ai.render(cached, verified)
    # No database lock spans the provider request. Meta sees only redacted,
    # verified scheduling facts and cannot mutate proposals or reservations.
    try:
        generated = recovery_ai.explain(verified)
    except integrations.IntegrationError as exc:
        fail(str(exc), 503)
    with transaction() as c:
        p = get(c, proposal_id, "proposal")
        current = verified_recovery(c, p)
        if current["snapshot_hash"] != verified["snapshot_hash"]:
            fail(
                "Scheduling inputs changed while Meta was explaining. Generate a fresh proposal or explanation."
            )
        record = dict(
            id=uid(),
            proposal_id=proposal_id,
            snapshot_hash=current["snapshot_hash"],
            created_at=stamp(),
            **generated,
        )
        put(c, "recovery_explanation", record)
        p["explanation_id"] = record["id"]
        put(c, "proposal", p)
        audit(
            c,
            p["job_id"],
            "recovery_explained",
            {
                "proposal_id": proposal_id,
                "model": record["model"],
                "snapshot_hash": current["snapshot_hash"],
            },
        )
        return recovery_ai.render(record, current)


@app.get("/api/proposals/{proposal_id}/explanation")
def get_recovery_explanation(proposal_id: str):
    with engine.connect() as c:
        p = get(c, proposal_id, "proposal")
        try:
            verified = verified_recovery(c, p)
        except HTTPException as exc:
            return {"status": "stale", "detail": exc.detail, "approval_required": True}
        if not p.get("explanation_id"):
            return {"status": "not_requested", "approval_required": True}
        record = get(c, p["explanation_id"], "recovery_explanation")
        if record["snapshot_hash"] != verified["snapshot_hash"]:
            return {
                "status": "stale",
                "detail": "Verified capacity changed; refresh the recovery proposal/explanation.",
                "approval_required": True,
            }
        return recovery_ai.render(record, verified)


class SelectRecoveryOption(BaseModel):
    option_id: str = Field(min_length=1, max_length=40)


@app.post("/api/proposals/{proposal_id}/select-option")
def select_recovery_option(proposal_id: str, body: SelectRecoveryOption):
    with transaction() as c:
        p = get(c, proposal_id, "proposal")
        verified_recovery(c, p)
        options = [p["choice"], *p["alternatives"]]
        chosen = next((o for o in options if o["option_id"] == body.option_id), None)
        if chosen is None:
            fail("Select an option from the verified proposal.", 422)
        if not chosen["on_time"]:
            fail("Late options require manual deadline review.", 422)
        p["choice"] = chosen
        p["alternatives"] = sorted(
            [o for o in options if o["option_id"] != body.option_id],
            key=lambda o: o["option_id"],
        )
        # The selected slot changes only the uncommitted proposal. The model does
        # not select for the operator and this endpoint cannot reserve capacity.
        job = get(c, p["job_id"], "job")
        p["message_draft"] = (
            f"Your job {job['title']} is proposed for {chosen['printer_name']}, completing {chosen['end']}. Your requested deadline remains feasible."
        )
        put(c, "proposal", p)
        audit(
            c,
            p["job_id"],
            "recovery_option_selected",
            {"proposal_id": proposal_id, "option_id": body.option_id},
        )
        return p


@app.post("/api/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: Approve):
    with transaction() as c:
        return approve_in_transaction(c, proposal_id, body)


def approve_in_transaction(c, proposal_id, body):
    p = get(c, proposal_id, "proposal")
    job = get(c, p["job_id"], "job")
    for approval in rows(c, "approval"):
        if approval["idempotency_key"] == body.idempotency_key:
            if approval["proposal_id"] != proposal_id:
                fail("Idempotency key belongs to another proposal")
            return approval["result"]
    if (
        p["status"] != "proposed"
        or p["job_version"] != job["version"]
        or parse(p["expires_at"]) <= now()
    ):
        fail("Proposal is stale; generate a new proposal")
    q = valid_quote(c, job)
    if q["id"] != p["quote_id"]:
        fail("Quote changed; generate a new proposal")
    if p["kind"] == "recovery" and p.get("explanation_id"):
        verified = verified_recovery(c, p)
        explanation = get(c, p["explanation_id"], "recovery_explanation")
        if explanation["snapshot_hash"] != verified["snapshot_hash"]:
            fail(
                "Meta explanation is stale because capacity changed. Refresh the proposal/explanation before approval."
            )
    expected = "recovery_required" if p["kind"] == "recovery" else "quote_ready"
    if job["status"] != expected:
        fail("Job state changed")
    choice = p["choice"]
    start = parse(choice["start"])
    end = parse(choice["end"])
    if not choice["on_time"]:
        fail(
            "Late plan requires a revised customer deadline and manual review; cannot approve in this MVP"
        )
    if start <= now():
        fail("Proposed start has passed; generate a new proposal")
    printer = get(c, choice["printer_id"], "printer")
    if (
        not printer["active"]
        or printer["material"] != job["material"]
        or printer["profile"] != q["profile"]
        or not all(a <= b for a, b in zip(q["dimensions_mm"], printer["bed_mm"]))
    ):
        fail("Printer compatibility changed")
    old = p["old_reservation"]
    if old and (job.get("reservation_id") != old["id"] or parse(old["start"]) <= now()):
        fail("Original reservation changed or started; manual review required")
    for r in rows(c, "reservation"):
        if (
            r["active"]
            and r["printer_id"] == printer["id"]
            and (not old or r["id"] != old["id"])
            and overlaps(start, end, parse(r["start"]), parse(r["end"]))
        ):
            fail("Capacity changed; generate a new proposal")
    for o in rows(c, "outage"):
        if o["printer_id"] == printer["id"] and overlaps(
            start, end, parse(o["starts_at"]), parse(o["ends_at"])
        ):
            fail("Printer outage conflicts; generate a new proposal")
    if old:
        old = get(c, old["id"], "reservation")
        old["active"] = False
        put(c, "reservation", old)
    r = dict(
        id=uid(),
        job_id=job["id"],
        printer_id=printer["id"],
        start=choice["start"],
        end=choice["end"],
        active=True,
        quote_id=q["id"],
    )
    put(c, "reservation", r)
    job.update(status="scheduled", reservation_id=r["id"], version=job["version"] + 1)
    put(c, "job", job)
    p["status"] = "approved"
    put(c, "proposal", p)
    audit(
        c,
        job["id"],
        "recovery_approved" if old else "plan_approved",
        {"reservation": r, "previous_reservation": old, "quote_id": q["id"]},
    )
    result = {"job": job, "reservation": r}
    put(
        c,
        "approval",
        dict(
            id=uid(),
            idempotency_key=body.idempotency_key,
            proposal_id=proposal_id,
            result=result,
        ),
    )
    return result


@app.post("/api/outages", status_code=201)
def outage(body: Outage):
    if body.ends_at <= body.starts_at:
        fail("Outage end must follow start", 422)
    with transaction() as c:
        get(c, body.printer_id, "printer")
        for old in rows(c, "outage"):
            if old["event_key"] == body.event_key:
                payload = body.model_dump(mode="json")
                if any(old[k] != v for k, v in payload.items()):
                    fail("Event key already used with different input")
                return old
        event = dict(
            id=uid(),
            **body.model_dump(mode="json"),
            source="operator_simulated",
            affected_jobs=[],
        )
        for r in rows(c, "reservation"):
            if (
                r["active"]
                and r["printer_id"] == body.printer_id
                and overlaps(
                    parse(r["start"]), parse(r["end"]), body.starts_at, body.ends_at
                )
            ):
                job = get(c, r["job_id"], "job")
                job["status"] = "recovery_required"
                job["version"] += 1
                put(c, "job", job)
                event["affected_jobs"].append(job["id"])
                audit(
                    c,
                    job["id"],
                    "printer_unavailable",
                    {"event_id": event["id"], "reason": body.reason, "simulated": True},
                )
        put(c, "outage", event)
        return event


@app.get("/api/jobs/{job_id}/preview")
def color_preview(job_id: str):
    with engine.connect() as c:
        job = get(c, job_id, "job")
        fingerprint = (job.get("file") or {}).get("preview_sha256")
        if not fingerprint or not (DATA / (fingerprint + ".glb")).is_file():
            fail("Color preview unavailable; re-upload the original 3MF", 404)
        return FileResponse(DATA / (fingerprint + ".glb"), media_type="model/gltf-binary")


@app.get("/api/jobs/{job_id}/mesh")
def mesh_file(job_id: str):
    with engine.connect() as c:
        job = get(c, job_id, "job")
        if not job["file"]:
            fail("No mesh uploaded", 404)
        return FileResponse(
            DATA / (job["file"]["sha256"] + ".stl"),
            media_type="application/octet-stream",
        )


from backend.comparison import register as register_comparison

register_comparison(app)

from backend.planner import register as register_planner

register_planner(app)

from backend.multicolor import register as register_multicolor

register_multicolor(app)

from backend.execution import register as register_execution

register_execution(app)

from backend.printer_connector import register as register_connector

register_connector(app)

from backend.printer_view import register as register_printer_view

register_printer_view(app)

DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
