import asyncio
import io
import json
import subprocess

import pytest
import trimesh
from fastapi import HTTPException, UploadFile

from backend import model_processing as processing
from backend.model_processing import execute_worker as real_worker


def request(tmp_path, mesh, repair=False):
    (tmp_path / "input.model").write_bytes(mesh.export(file_type="stl"))
    (tmp_path / "request.json").write_text(
        json.dumps(dict(filename="sample.stl", repair=repair)), encoding="utf-8"
    )


def test_real_worker_accepts_model_above_old_size_and_triangle_limits(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=7)
    assert len(mesh.faces) > 250_000
    request(tmp_path, mesh)
    assert (tmp_path / "input.model").stat().st_size > 10 * 1024 * 1024
    metadata, normalized, _ = real_worker(tmp_path)
    assert metadata["watertight"] and metadata["triangles"] == len(mesh.faces)
    assert json.loads((tmp_path / "response.json").read_text())["memory_limit_enforced"]
    assert len(normalized) == len(mesh.faces) * 50 + 84


def test_real_worker_does_not_expand_automatic_repair_limit(tmp_path):
    request(tmp_path, trimesh.creation.icosphere(subdivisions=7), repair=True)
    with pytest.raises(HTTPException) as error:
        real_worker(tmp_path, True)
    assert "250,000" in error.value.detail


def test_worker_timeout_and_environment_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "unit-secret-no-network")
    monkeypatch.setenv("DATABASE_URL", "private-test-database")

    def timeout(*args, **kwargs):
        assert "META_API_KEY" not in kwargs["env"]
        assert "DATABASE_URL" not in kwargs["env"]
        assert kwargs["timeout"] == 90
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(processing.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as error:
        real_worker(tmp_path)
    assert "timed out" in error.value.detail


def test_stream_limit_cleans_temp_files_and_releases_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(processing, "MAX_UPLOAD_BYTES", 10)
    upload = UploadFile(file=io.BytesIO(b"x" * 11), filename="part.stl")
    with pytest.raises(HTTPException) as error:
        asyncio.run(processing.process_upload(upload, tmp_path))
    assert error.value.status_code == 413
    assert not list((tmp_path / "processing").iterdir())
    assert processing._slot.acquire(blocking=False)
    processing._slot.release()


def test_busy_worker_returns_retry_without_processing(tmp_path):
    assert processing._slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                processing.process_upload(
                    UploadFile(file=io.BytesIO(b"x"), filename="part.stl"), tmp_path
                )
            )
        assert error.value.status_code == 429
    finally:
        processing._slot.release()


def test_real_api_upload_uses_worker_and_does_not_create_job(client, monkeypatch):
    monkeypatch.setattr(processing, "execute_worker", real_worker)
    response = client.post(
        "/api/model-uploads",
        files={"file": ("box.stl", trimesh.creation.box().export(file_type="stl"))},
    )
    assert response.status_code == 201, response.text
    assert response.json()["file"]["watertight"]
    assert not client.get("/api/state").json()["jobs"]


def test_profile_project_generation_uses_limited_worker(tmp_path):
    from backend.tests.test_project_profile import project_file
    from backend.project_profile import read_project

    source = project_file(tmp_path)
    project = read_project(source)
    mesh = tmp_path / "sample.stl"
    mesh.write_bytes(trimesh.creation.box().export(file_type="stl"))
    target = tmp_path / "generated.3mf"
    processing.build_profile_project(project, mesh, "mm", target)
    assert read_project(target)["filament_slot"] == 2
    assert not list(tmp_path.glob("project-*"))
