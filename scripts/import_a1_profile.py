"""Import private A1 or A1 mini PLA settings; replace source geometry with the owned sample."""

import argparse
import json
import os
from pathlib import Path
from backend.project_profile import read_project, write_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project = read_project(args.project)
    machine = project["settings"]["printer_model"]
    if machine not in ("Bambu Lab A1", "Bambu Lab A1 mini"):
        raise ValueError("This importer requires an A1 or A1 mini project.")
    root = Path(__file__).resolve().parents[1]
    slug = "a1mini" if machine == "Bambu Lab A1 mini" else "a1"
    label = "A1 mini" if slug == "a1mini" else "A1"
    target = root / f"data/local-profiles/{slug}-pla-reference.3mf"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    write_project(project, root / "samples/demo-block.stl", "mm", temporary)
    os.replace(temporary, target)
    manifest = root / "profiles/registry.json"
    source = manifest if manifest.exists() else root / "profiles/registry.example.json"
    registry = json.loads(source.read_text(encoding="utf-8"))
    profile = dict(
        id=f"{slug}-pla-0.4-v1",
        name=f"{label} / Generic PLA / 0.4 mm / saved project",
        source="bambu_project",
        project=f"data/local-profiles/{slug}-pla-reference.3mf",
        bed_mm=project["bed_mm"],
        calibrated=False,
        printer={"id": f"bambu-{slug}", "name": machine},
    )
    registry["profiles"] = [
        p for p in registry["profiles"] if p["id"] != profile["id"]
    ] + [profile]
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest)
    print(
        f"{label} settings imported locally. Source geometry not retained; calibration remains unverified."
    )


if __name__ == "__main__":
    main()
