import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "test.db").as_posix())
    from backend import main
    from backend import model_processing
    from backend.model_geometry import inspect

    # Unit tests exercise the pure geometry path quickly. Separate worker tests
    # below verify real process isolation, resource setup and timeout handling.
    def inline_worker(directory, repair=False):
        import json
        from fastapi import HTTPException
        from backend.mesh_upload import MeshImportError

        config = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        try:
            return inspect(
                (directory / "input.model").read_bytes(), config["filename"], repair,
                preview_path=directory / "preview.glb"
            )
        except MeshImportError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(422, "Model could not be parsed") from None

    monkeypatch.setattr(model_processing, "execute_worker", inline_worker)

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c
    main.engine.dispose()
