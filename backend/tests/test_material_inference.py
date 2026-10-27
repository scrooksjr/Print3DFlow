import io
import json
from zipfile import ZipFile
from datetime import datetime, timedelta, timezone

import pytest

from backend.mesh_upload import import_3mf
from backend.tests.test_colors import color_project
from backend.tests.test_integrations import mock_meta, draft_payload


def material_project(types, slots=(2,), paint=False):
    with ZipFile(io.BytesIO(color_project(slots=slots, paint=paint))) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    settings = json.loads(parts["Metadata/project_settings.config"])
    settings["filament_type"] = types
    parts["Metadata/project_settings.config"] = json.dumps(settings).encode()
    result = io.BytesIO()
    with ZipFile(result, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return result.getvalue()


def test_only_used_slot_materials_drive_suggestion():
    info = import_3mf(material_project(["ABS", "PETG", "TPU", "PLA"])).metadata[
        "color_info"
    ]
    assert info["material_inference"]["suggested_material"] == "PETG"
    assert info["material_inference"]["assigned_materials"] == ["PETG"]


@pytest.mark.parametrize(
    "types,slots,status",
    [
        (["PLA"] * 4, (), "missing_assignments"),
        (["PLA", "PETG", "ABS", "TPU"], (1, 2), "conflicting_materials"),
        (["PLA+"] * 4, (2,), "unsupported_material"),
    ],
)
def test_ambiguous_or_unknown_material_is_not_defaulted(types, slots, status):
    inference = import_3mf(material_project(types, slots)).metadata["color_info"][
        "material_inference"
    ]
    assert inference["suggested_material"] is None
    assert inference["status"] == status and inference["clarification"]


def test_painted_regions_cannot_be_inferred_from_the_base_slot():
    info = import_3mf(material_project(["PLA"] * 4, paint=True)).metadata["color_info"]
    assert info["material_inference"]["suggested_material"] is None
    assert info["material_inference"]["status"] == "unresolved_assignments"
    assert info["quoting_blocked"]


def test_intake_uses_file_suggestion_and_supports_explicit_review_override(
    client, monkeypatch
):
    staged = client.post(
        "/api/model-uploads",
        files={"file": ("part.3mf", material_project(["PLA"] * 4))},
    ).json()
    mock_meta(monkeypatch, draft_payload(material=None))
    result = client.post(
        "/api/intake/drafts",
        json=dict(
            request="Three copies of the attached part", model_upload_id=staged["id"]
        ),
    ).json()
    assert result["draft"]["material"] == "PLA"
    body = dict(
        title="Reviewed print",
        request=result["request"],
        quantity=3,
        units="mm",
        material="PETG",
        deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        model_upload_id=staged["id"],
        intake_draft_id=result["id"],
        ai_review_confirmed=True,
    )
    assert client.post("/api/jobs", json=body).status_code == 422
    r = client.post("/api/jobs", json=dict(body, material_override_confirmed=True))
    assert r.status_code == 201, r.text
    assert (
        r.json()["material"] == "PETG"
        and r.json()["status"] == "awaiting_material_profile"
    )


def test_model_cannot_invent_pla_for_missing_assignments(client, monkeypatch):
    staged = client.post(
        "/api/model-uploads",
        files={"file": ("part.3mf", material_project(["PLA"] * 4, slots=()))},
    ).json()
    mock_meta(monkeypatch, draft_payload(material="PLA"))
    r = client.post(
        "/api/intake/drafts",
        json=dict(
            request="Three copies of the attached part", model_upload_id=staged["id"]
        ),
    ).json()
    assert r["draft"]["material"] is None
    assert "material" in r["missing_fields"]
    assert any("filament" in q.lower() for q in r["draft"]["questions"])
