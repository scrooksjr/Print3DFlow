import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend import integrations
from backend.tests.test_workflow import job, plan, approve


def draft_payload(**changes):
    draft = dict(
        title="Mounting blocks",
        quantity=3,
        material="PLA",
        color=None,
        units="mm",
        deadline=(datetime.now(timezone.utc) + timedelta(days=4)).isoformat(),
        finish=None,
        questions=[],
        warnings=[],
    )
    return draft | changes


def mock_meta(monkeypatch, content=None, status=200, finish="stop"):
    monkeypatch.setenv("META_API_KEY", "unit-test-key-not-a-secret")
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3")
    original = integrations.httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {"content": json.dumps(content or draft_payload())},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        integrations.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return requests


def test_missing_meta_key_is_explicit_and_no_job_created(client, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "")
    r = client.post("/api/intake/drafts", json={"request": "Three PLA blocks"})
    assert r.status_code == 503
    assert "META_API_KEY" in r.json()["detail"]
    assert client.get("/api/state").json()["jobs"] == []


def test_meta_draft_is_review_only_and_uses_official_schema(client, monkeypatch):
    requests = mock_meta(monkeypatch)
    r = client.post(
        "/api/intake/drafts", json={"request": "Three PLA blocks, STL in mm"}
    )
    assert r.status_code == 201, r.text
    result = r.json()
    assert result["review_required"] and result["source"] == "meta_model_api"
    assert not client.get("/api/state").json()["jobs"]
    sent = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://api.meta.ai/v1/chat/completions"
    assert (
        sent["response_format"]["json_schema"]["schema"]["additionalProperties"]
        is False
    )
    assert "tools" not in sent
    body = dict(
        title=result["draft"]["title"],
        request=result["request"],
        quantity=3,
        units="mm",
        deadline=result["draft"]["deadline"],
        intake_draft_id=result["id"],
    )
    import trimesh

    mesh = trimesh.creation.box(extents=[3, 2, 1]).export(file_type="stl")
    body["model_upload_id"] = client.post(
        "/api/model-uploads", files={"file": ("part.stl", mesh)}
    ).json()["id"]
    assert client.post("/api/jobs", json=body).status_code == 422
    body["ai_review_confirmed"] = True
    assert client.post("/api/jobs", json=body).status_code == 201


def test_missing_and_unsupported_fields_require_clarification(client, monkeypatch):
    mock_meta(
        monkeypatch,
        draft_payload(quantity=None, units=None, deadline=None, material="PETG"),
    )
    result = client.post(
        "/api/intake/drafts", json={"request": "PETG brackets sometime next week"}
    ).json()
    assert set(result["missing_fields"]) == {"quantity", "units", "deadline"}
    assert result["draft"]["quantity"] is None
    assert len(result["draft"]["questions"]) >= 3
    assert any("PLA only" in w for w in result["draft"]["warnings"])


def test_file_context_uses_validated_units_and_medium_size_question(
    client, monkeypatch
):
    from backend.tests.test_mesh_upload import model_file

    staged = client.post(
        "/api/model-uploads",
        files={"file": ("private-name.3mf", model_file("centimeter"))},
    ).json()
    sent = mock_meta(
        monkeypatch,
        draft_payload(
            material="ABS",
            color="black",
            units=None,
            questions=[
                "What object should be printed? Please provide a file.",
                "What units does the STL use?",
            ],
            warnings=[
                "Material ABS is unsupported; MVP supports PLA only.",
                "ABS material is unsupported.",
            ],
        ),
    )
    r = client.post(
        "/api/intake/drafts",
        json=dict(
            request="I want a medium sized print, in ABS black.",
            model_upload_id=staged["id"],
        ),
    )
    assert r.status_code == 201, r.text
    result = r.json()
    d = result["draft"]
    assert d["units"] == "mm" and d["material"] == "ABS"
    assert result["file_context"]["dimensions_native"] == [30, 20, 10]
    assert result["file_context"]["embedded_units"] == "centimeter"
    assert "units" not in result["missing_fields"]
    assert result["size_review_required"]
    assert len(d["questions"]) == 1 and "exact" in d["questions"][0]
    assert len(d["warnings"]) == 1
    payload = json.loads(sent[0].content)
    context = json.loads(payload["messages"][1]["content"])["validated_file"]
    assert context["format"] == "3mf" and context["geometry_units"] == "mm"
    assert "private-name" not in sent[0].content.decode()
    assert not client.get("/api/state").json()["jobs"]
    body = dict(
        title="ABS print",
        request=result["request"],
        material="PLA",
        quantity=1,
        units="mm",
        deadline=d["deadline"],
        intake_draft_id=result["id"],
        ai_review_confirmed=True,
        model_upload_id=staged["id"],
    )
    assert client.post("/api/jobs", json=body).status_code == 422


def test_file_aware_draft_cannot_be_reused_for_different_model(client, monkeypatch):
    import trimesh

    mesh = trimesh.creation.box().export(file_type="stl")
    first = client.post(
        "/api/model-uploads", files={"file": ("first.stl", mesh)}
    ).json()
    second = client.post(
        "/api/model-uploads", files={"file": ("second.stl", mesh)}
    ).json()
    mock_meta(monkeypatch, draft_payload())
    d = client.post(
        "/api/intake/drafts",
        json=dict(request="Three PLA blocks in mm", model_upload_id=first["id"]),
    ).json()
    body = dict(
        title="Blocks",
        request=d["request"],
        quantity=3,
        units="mm",
        deadline=d["draft"]["deadline"],
        model_upload_id=second["id"],
        intake_draft_id=d["id"],
        ai_review_confirmed=True,
    )
    assert client.post("/api/jobs", json=body).status_code == 422


def test_stl_context_does_not_invent_embedded_units(client, monkeypatch):
    import trimesh

    stage = client.post(
        "/api/model-uploads",
        files={"file": ("part.stl", trimesh.creation.box().export(file_type="stl"))},
    ).json()
    mock_meta(monkeypatch, draft_payload(units=None, questions=[]))
    r = client.post(
        "/api/intake/drafts",
        json=dict(request="Three PLA blocks", model_upload_id=stage["id"]),
    ).json()
    assert r["file_context"]["embedded_units"] is None and r["draft"]["units"] is None
    assert "units" in r["missing_fields"]


def test_pla_color_is_not_rejected_and_questions_are_deduplicated(client, monkeypatch):
    mock_meta(
        monkeypatch,
        draft_payload(
            material="PLA white",
            units=None,
            deadline=None,
            questions=[
                "What units should the STL use?",
                "What scale is the file?",
                "Is there a deadline?",
                "What completion date is required?",
            ],
        ),
    )
    result = client.post(
        "/api/intake/drafts", json={"request": "Print as is, three ghosts in PLA white"}
    ).json()
    assert result["draft"]["material"] == "PLA" and result["draft"]["color"] == "white"
    assert len(result["draft"]["questions"]) == 2
    assert not any("PLA only" in w for w in result["draft"]["warnings"])


@pytest.mark.parametrize("material", ["PLA+", "silk PLA", "PLA PETG blend"])
def test_modified_materials_still_require_review(client, monkeypatch, material):
    mock_meta(monkeypatch, draft_payload(material=material))
    result = client.post(
        "/api/intake/drafts", json={"request": "Three parts in " + material}
    ).json()
    assert result["draft"]["material"] == material
    assert any("PLA only" in w for w in result["draft"]["warnings"])


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_errors_are_sanitized(client, monkeypatch, status):
    mock_meta(monkeypatch, status=status)
    r = client.post("/api/intake/drafts", json={"request": "Three PLA blocks"})
    assert r.status_code == 503
    assert "unit-test-key" not in r.text
    assert not client.get("/api/state").json()["jobs"]


def test_invalid_or_truncated_meta_output_is_rejected(client, monkeypatch):
    mock_meta(monkeypatch, content={"arbitrary": "unvalidated"}, finish="length")
    r = client.post("/api/intake/drafts", json={"request": "Three PLA blocks"})
    assert r.status_code == 503


def test_naive_model_deadline_is_not_accepted(client, monkeypatch):
    mock_meta(monkeypatch, draft_payload(deadline="2030-01-01T12:00:00"))
    result = client.post(
        "/api/intake/drafts", json={"request": "Some PLA blocks"}
    ).json()
    assert result["draft"]["deadline"] is None
    assert "deadline" in result["missing_fields"]


def fake_profile(profile_id="demo-pla-0.2-v1"):
    return (
        {
            "id": profile_id,
            "bed_mm": [220, 220, 250],
            "name": "test profile",
            "calibrated": False,
        },
        {},
        "test-fingerprint",
    )


def fake_slice(*args):
    return dict(
        grams_per_part=3.5,
        hours_per_part=0.25,
        profile_id="demo-pla-0.2-v1",
        profile_name="Test fixture, not actual slicing",
        profile_sha256="test-fingerprint",
        executable_sha256="test-exe",
        report_sha256="test-report",
        calibrated=False,
        settings=dict(
            layer_height_mm=0.2,
            infill_percent=20,
            walls=3,
            supports=False,
            nozzle_mm=0.4,
        ),
    )


def setup_slice(monkeypatch, tmp_path):
    executable = tmp_path / "fake-exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(integrations, "bambu_executable", lambda: executable)
    monkeypatch.setattr(integrations, "load_profile", fake_profile)
    monkeypatch.setattr(integrations, "run_bambu_slice", fake_slice)


def test_slice_task_generates_quote_used_by_scheduler(client, monkeypatch, tmp_path):
    setup_slice(monkeypatch, tmp_path)
    key = job(client)
    body = dict(confirmed=True, idempotency_key="slice-task-unique")
    response = client.post(f"/api/jobs/{key}/slice-quotes", json=body)
    assert response.status_code == 202, response.text
    task_id = response.json()["id"]
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "succeeded", task
    assert (
        client.post(f"/api/jobs/{key}/slice-quotes", json=body).json()["id"] == task_id
    )
    quote = next(
        q
        for q in client.get("/api/state").json()["quotes"]
        if q["id"] == task["quote_id"]
    )
    assert quote["source"] == "bambu_studio"
    assert quote["grams"] == 10.5 and quote["duration_minutes"] == 75
    p = plan(client, key)
    assert approve(client, p).status_code == 200


def test_failed_slice_never_falls_back_to_invented_quote(client, monkeypatch, tmp_path):
    setup_slice(monkeypatch, tmp_path)

    def bad(*args):
        raise integrations.IntegrationError("Slicing exceeded the time limit")

    monkeypatch.setattr(integrations, "run_bambu_slice", bad)
    key = job(client)
    r = client.post(
        f"/api/jobs/{key}/slice-quotes",
        json=dict(confirmed=True, idempotency_key="failed-slice-key"),
    )
    task = client.get("/api/tasks/" + r.json()["id"]).json()
    assert task["status"] == "failed"
    assert client.get("/api/state").json()["quotes"] == []


def test_slicing_result_does_not_overwrite_changed_job(client, monkeypatch, tmp_path):
    setup_slice(monkeypatch, tmp_path)
    from backend import main

    key = job(client)

    def changed(*args):
        with main.transaction() as c:
            j = main.get(c, key, "job")
            j["version"] += 1
            j["requirements_version"] += 1
            main.put(c, "job", j)
        return fake_slice()

    monkeypatch.setattr(integrations, "run_bambu_slice", changed)
    r = client.post(
        f"/api/jobs/{key}/slice-quotes",
        json=dict(confirmed=True, idempotency_key="stale-slice-key"),
    )
    task = client.get("/api/tasks/" + r.json()["id"]).json()
    assert task["status"] == "failed" and "changed" in task["error"]
    assert not client.get("/api/state").json()["quotes"]


def test_profile_change_invalidates_slice_quote_approval(client, monkeypatch, tmp_path):
    setup_slice(monkeypatch, tmp_path)
    key = job(client)
    client.post(
        f"/api/jobs/{key}/slice-quotes",
        json=dict(confirmed=True, idempotency_key="profile-change-key"),
    )
    p = plan(client, key)
    monkeypatch.setattr(
        integrations,
        "load_profile",
        lambda key: (fake_profile()[0], {}, "changed-fingerprint"),
    )
    assert approve(client, p).status_code == 409


@pytest.mark.parametrize(
    "plate",
    [
        {},
        {"total_predication": float("nan"), "filaments": [{"total_used_g": 3}]},
        {"total_predication": 30, "filaments": [{"total_used_g": 0}]},
        {
            "total_predication": 30,
            "filaments": [{"total_used_g": 3}],
            "warning_message": "manual review",
        },
    ],
)
def test_malformed_or_warned_slicer_report_is_rejected(plate):
    with pytest.raises(integrations.IntegrationError):
        integrations.parse_bambu_report({"return_code": 0, "sliced_plates": [plate]})


def test_slicer_runner_is_shell_free_and_does_not_inherit_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("META_API_KEY", "must-not-leak-to-slicer")
    # Exercise the real adapter, replace only the external executable boundary.
    executable = tmp_path / "fake-exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(integrations, "bambu_executable", lambda: executable)
    configs = {k: {} for k in ("machine", "process", "filament")}
    configs["machine"] = {"nozzle_diameter": ["0.4"]}
    configs["process"] = {
        "layer_height": "0.2",
        "sparse_infill_density": "20%",
        "wall_loops": "3",
    }
    monkeypatch.setattr(
        integrations,
        "load_profile",
        lambda key: (fake_profile()[0], configs, "test-fingerprint"),
    )
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        (Path(kwargs["cwd"]) / "result.json").write_text(
            json.dumps(
                {
                    "return_code": 0,
                    "sliced_plates": [
                        {"total_predication": 60, "filaments": [{"total_used_g": 2}]}
                    ],
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(integrations.subprocess, "run", runner)
    mesh = tmp_path / "input with spaces.stl"
    mesh.write_text("fixture")
    result = integrations.run_bambu_slice(
        mesh, "cm", "demo-pla-0.2-v1", tmp_path / "out"
    )
    assert result["grams_per_part"] == 2
    args, kwargs = calls[0]
    assert "shell" not in kwargs and kwargs["timeout"] == 120
    assert "META_API_KEY" not in kwargs["env"]
    assert args[args.index("--scale") + 1] == "10"
    assert args[-1] == str(mesh.resolve())


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SLICER") != "1",
    reason="Opt-in local Bambu Studio integration test",
)
def test_live_bambu_slice_quote_reservation_and_recovery(client):
    key = job(client)
    r = client.post(
        f"/api/jobs/{key}/slice-quotes",
        json={"confirmed": True, "idempotency_key": "real-bambu-slice-test"},
    )
    assert r.status_code == 202, r.text
    task = client.get("/api/tasks/" + r.json()["id"]).json()
    assert task["status"] == "succeeded", task
    report = client.get("/api/tasks/" + task["id"] + "/report")
    assert report.status_code == 200
    assert report.json()["return_code"] == 0
    q = next(
        q
        for q in client.get("/api/state").json()["quotes"]
        if q["id"] == task["quote_id"]
    )
    assert q["source"] == "bambu_studio" and q["grams"] > 0 and q["hours"] > 0
    assert len(q["slicer"]["profile_sha256"]) == 64
    reserved = approve(client, plan(client, key)).json()["reservation"]
    event = client.post(
        "/api/outages",
        json={
            "printer_id": reserved["printer_id"],
            "starts_at": datetime.now(timezone.utc).isoformat(),
            "ends_at": (
                datetime.fromisoformat(reserved["end"]) + timedelta(hours=4)
            ).isoformat(),
            "reason": "Synthetic integration test outage",
            "event_key": "real-slice-recovery-event",
        },
    )
    assert event.status_code == 201
    recovery = client.post(f"/api/jobs/{key}/recovery").json()
    assert recovery["choice"]["printer_id"] != reserved["printer_id"]
    assert approve(client, recovery, "real-slice-recovery-approval").status_code == 200
