from datetime import datetime, timedelta, timezone

import pytest
import trimesh

from backend.tests.test_mesh_upload import model_file


def body(**extra):
    return dict(
        title="New job",
        units="mm",
        deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        **extra,
    )


def test_job_cannot_be_created_without_model(client):
    assert client.post("/api/jobs", json=body()).status_code == 422
    assert not client.get("/api/state").json()["jobs"]


@pytest.mark.parametrize(
    "name,content",
    [("bad.stl", b"invalid"), ("bad.3mf", b"invalid"), ("part.txt", b"invalid")],
)
def test_invalid_model_never_creates_job(client, name, content):
    assert (
        client.post("/api/model-uploads", files={"file": (name, content)}).status_code
        == 422
    )
    assert not client.get("/api/state").json()["jobs"]


@pytest.mark.parametrize("name", ["part.stl", "part.3mf"])
def test_creation_attaches_valid_geometry_and_consumes_upload_once(client, name):
    content = (
        model_file("centimeter")
        if name.endswith("3mf")
        else trimesh.creation.box().export(file_type="stl")
    )
    staged = client.post("/api/model-uploads", files={"file": (name, content)})
    assert staged.status_code == 201, staged.text
    assert not client.get("/api/state").json()["jobs"]
    request = body(model_upload_id=staged.json()["id"])
    response = client.post("/api/jobs", json=request)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["file"]["filename"] == name and job["status"] == "ready_for_quote"
    assert client.get("/api/jobs/" + job["id"] + "/mesh").status_code == 200
    assert client.post("/api/jobs", json=request).status_code == 409
    assert len(client.get("/api/state").json()["jobs"]) == 1


def test_expired_upload_cannot_create_job(client):
    from backend import main as m

    staged = client.post(
        "/api/model-uploads",
        files={"file": ("box.stl", trimesh.creation.box().export(file_type="stl"))},
    ).json()
    with m.transaction() as c:
        upload = m.get(c, staged["id"], "model_upload")
        upload["expires_at"] = (m.now() - timedelta(seconds=1)).isoformat()
        m.put(c, "model_upload", upload)
    assert (
        client.post("/api/jobs", json=body(model_upload_id=staged["id"])).status_code
        == 409
    )
    assert not client.get("/api/state").json()["jobs"]
