"""Import only settings and mappings from a one-part X2D Bambu project.

Run from the project root: .venv/Scripts/python.exe -m scripts.import_x2d_profile PATH
The imported model and ancillary assets are not retained.
"""

import argparse
import json
import os
from pathlib import Path

from backend.project_profile import read_project, write_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = read_project(args.project)
    target = root / "data/local-profiles/x2d-pla-reference.3mf"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    write_project(project, root / "samples/demo-block.stl", "mm", temporary)
    os.replace(temporary, target)
    manifest = root / "profiles/registry.json"
    registry_source = (
        manifest if manifest.exists() else root / "profiles/registry.example.json"
    )
    registry = json.loads(registry_source.read_text(encoding="utf-8"))
    profile = dict(
        id="x2d-pla-0.4-v1",
        name="X2D / Generic PLA / 0.4 mm / saved project",
        source="bambu_project",
        project="data/local-profiles/x2d-pla-reference.3mf",
        bed_mm=project["bed_mm"],
        calibrated=False,
        printer={"id": "bambu-x2d", "name": "Bambu Lab X2D"},
    )
    registry["profiles"] = [
        p for p in registry["profiles"] if p["id"] != profile["id"]
    ] + [profile]
    temporary_manifest = manifest.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(registry, indent=2) + "\n")
    os.replace(temporary_manifest, manifest)
    print(
        "X2D settings imported. Restart the app, then validate a sample quote before use."
    )
    print(
        "Original model not retained. Calibration and live printer telemetry remain unverified."
    )


if __name__ == "__main__":
    main()
