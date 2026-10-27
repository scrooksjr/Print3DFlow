"""Child entrypoint: establish OS limits before importing geometry libraries."""

import json
import os
import sys
from pathlib import Path

from backend.model_limits import WORKER_MEMORY_BYTES, MAX_UPLOAD_BYTES

_job = None


def apply_limits():
    global _job
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        _job = k.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100 | 0x2000
        info.process_memory = WORKER_MEMORY_BYTES
        if (
            not _job
            or not k.SetInformationJobObject(
                _job, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            or not k.AssignProcessToJobObject(_job, k.GetCurrentProcess())
        ):
            raise RuntimeError("Could not establish worker memory limit")
    elif os.name == "posix":
        import resource

        resource.setrlimit(
            resource.RLIMIT_AS, (WORKER_MEMORY_BYTES, WORKER_MEMORY_BYTES)
        )
    else:
        raise RuntimeError("OS memory limits unsupported")


def main():
    directory = Path(sys.argv[1])
    phase = "limits"
    try:
        apply_limits()
        config = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        source = directory / "input.model"
        if source.stat().st_size > MAX_UPLOAD_BYTES:
            raise ValueError("Input exceeds processing size limit")
        if config.get("operation") == "project":
            phase = "project"
            from backend.project_profile import write_project

            write_project(
                config["project"], source, config["units"], directory / "project.3mf"
            )
            (directory / "response.json").write_text(
                json.dumps(dict(ok=True, memory_limit_enforced=True)), encoding="utf-8"
            )
            return
        from backend.model_geometry import inspect
        from backend.mesh_upload import MeshImportError

        try:
            phase = "inspection"
            metadata, normalized, report = inspect(
                source.read_bytes(), config["filename"], config["repair"]
            )
        except MeshImportError as exc:
            result = dict(ok=False, error=str(exc))
        else:
            phase = "output"
            (directory / "normalized.stl").write_bytes(normalized)
            result = dict(
                ok=True, file=metadata, report=report, memory_limit_enforced=True
            )
    except BaseException as exc:
        result = dict(
            ok=False,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "errno", None),
            windows_error=getattr(exc, "winerror", None),
            phase=phase,
            error="Model processing exceeded resources or could not complete. Simplify the model or repair it externally.",
        )
    (directory / "response.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
