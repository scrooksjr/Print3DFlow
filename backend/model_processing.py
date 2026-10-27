"""One model process at a time, bounded disk buffers, deadline and minimal environment."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from backend.model_limits import (
    MAX_UPLOAD_BYTES,
    MAX_NORMALIZED_BYTES,
    INSPECTION_SECONDS,
    REPAIR_SECONDS,
)

_slot = threading.BoundedSemaphore(1)
ROOT = Path(__file__).resolve().parents[1]


def invoke_worker(directory, repair=False):
    environment = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG")
    }
    environment.update(
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONUTF8="1",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "backend.model_worker", str(directory)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=REPAIR_SECONDS if repair else INSPECTION_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            422,
            "Model processing timed out. Simplify the model or repair it externally.",
        ) from None
    except OSError:
        raise HTTPException(
            503, "Model worker could not start; retry or review the installation"
        ) from None
    response = directory / "response.json"
    if result.returncode or not response.is_file() or response.stat().st_size > 32768:
        raise HTTPException(
            422,
            "Model worker stopped or exceeded its memory limit. Simplify the model.",
        )
    output = json.loads(response.read_text(encoding="utf-8"))
    if not output.get("ok"):
        raise HTTPException(422, output.get("error", "Model processing failed"))
    return output


def execute_worker(directory, repair=False):
    output = invoke_worker(directory, repair)
    normalized = directory / "normalized.stl"
    if not normalized.is_file() or normalized.stat().st_size > MAX_NORMALIZED_BYTES:
        raise HTTPException(422, "Normalized model exceeds processing limits")
    return output["file"], normalized.read_bytes(), output.get("report")


def build_profile_project(project, mesh, units, target):
    """Bound the XML-heavy serialization step before native Bambu slicing too."""
    if mesh.stat().st_size > MAX_NORMALIZED_BYTES:
        raise HTTPException(422, "Normalized mesh exceeds project-generation limit")
    if not _slot.acquire(timeout=INSPECTION_SECONDS):
        raise HTTPException(429, "Model worker is busy; retry slicing")
    try:
        with tempfile.TemporaryDirectory(
            dir=target.parent, prefix="project-"
        ) as folder:
            directory = Path(folder)
            shutil.copyfile(mesh, directory / "input.model")
            (directory / "request.json").write_text(
                json.dumps(dict(operation="project", project=project, units=units)),
                encoding="utf-8",
            )
            invoke_worker(directory)
            output = directory / "project.3mf"
            if not output.is_file() or output.stat().st_size > 128 * 1024 * 1024:
                raise HTTPException(422, "Generated slicing project exceeds limit")
            shutil.copyfile(output, target)
    finally:
        _slot.release()


async def process_upload(file, data, repair=False):
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in (".stl", ".3mf"):
        raise HTTPException(422, "Only STL and 3MF files are supported")
    if not _slot.acquire(blocking=False):
        raise HTTPException(
            429, "Another model is being inspected or repaired. Retry when it finishes."
        )
    try:
        parent = data / "processing"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent, prefix="model-") as folder:
            directory = Path(folder)
            total = 0
            with (directory / "input.model").open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            413, "Model file exceeds the 64 MiB upload limit"
                        )
                    destination.write(chunk)
            (directory / "request.json").write_text(
                json.dumps(dict(filename=filename, repair=repair)), encoding="utf-8"
            )
            return await run_in_threadpool(execute_worker, directory, repair)
    finally:
        _slot.release()
