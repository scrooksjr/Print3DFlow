from datetime import datetime, timedelta, timezone
import trimesh


def test_repair_is_a_reviewed_copy_before_job_creation(client):
    m = trimesh.creation.box()
    m.update_faces([True] * 11 + [False])
    original = m.export(file_type="stl")
    r = client.post("/api/model-repairs", files={"file": ("open.stl", original)})
    assert r.status_code == 201, r.text
    repair = r.json()
    assert repair["approval_required"] and repair["report"]["after"]["watertight"]
    assert not repair["report"]["before"]["watertight"]
    assert repair["report"]["added_faces"] == 1
    assert (
        repair["report"]["before"]["dimensions_mm_or_native"]
        == repair["report"]["after"]["dimensions_mm_or_native"]
    )
    assert not client.get("/api/state").json()["jobs"]
    assert client.get(repair["download_url"]).content != original
    body = dict(
        title="Repaired part",
        units="mm",
        deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        model_upload_id=repair["id"],
    )
    assert client.post("/api/jobs", json=body).status_code == 422
    assert (
        client.post(
            "/api/intake/drafts",
            json={"request": "Three PLA parts", "model_upload_id": repair["id"]},
        ).status_code
        == 422
    )
    url = "/api/model-repairs/" + repair["id"] + "/approve"
    assert client.post(url, json={"confirmed": False}).status_code == 422
    assert client.post(url, json={"confirmed": True}).status_code == 200
    assert client.post("/api/jobs", json=body).status_code == 201
    assert not client.get("/api/state").json()["reservations"]


def test_unrepairable_mesh_stays_blocked_without_creating_a_job(client):
    # A single open triangle is not an enclosed 3D solid.
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 1], [0, 1, 0]], faces=[[0, 1, 2]]
    )
    r = client.post(
        "/api/model-repairs", files={"file": ("open.stl", mesh.export(file_type="stl"))}
    )
    assert r.status_code == 422
    assert not client.get("/api/state").json()["jobs"]
