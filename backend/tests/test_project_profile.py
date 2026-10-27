import json
import os
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
import trimesh

from backend.project_profile import CORE, read_project, write_project
from backend.tests.test_workflow import job, plan, approve


def project_file(tmp_path, **changes):
    settings = dict(
        printer_model="Bambu Lab X2D",
        nozzle_diameter=["0.4", "0.4"],
        filament_type=["PLA"] * 4,
        post_process=[],
        extruder_printable_area=[
            "0x0,256x0,256x256,0x256",
            "20.5x0,256x0,256x256,20.5x256",
        ],
        extruder_printable_height=["261", "256"],
    )
    settings.update(changes)
    p = tmp_path / "fixture.3mf"
    with ZipFile(p, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps(settings))
        z.writestr(
            "Metadata/model_settings.config",
            '<config><object id="7"><metadata key="name" value="original-private-model"/><metadata key="extruder" value="2"/><part id="6" subtype="normal_part"/></object><plate><metadata key="filament_map_mode" value="Auto For Quality"/><metadata key="filament_maps" value="1 1 1 1"/></plate></config>',
        )
        z.writestr(
            "Auxiliaries/private.txt", "Do not carry this artifact into another quote"
        )
    return p


def test_profile_preserves_slot_and_conservative_envelope(tmp_path):
    profile = read_project(project_file(tmp_path))
    assert profile["filament_slot"] == 2
    assert profile["bed_mm"] == [235.5, 256, 256]
    assert profile["plate_mapping"]["filament_maps"] == "1 1 1 1"


@pytest.mark.parametrize(
    "machine,size", [("Bambu Lab A1", 256), ("Bambu Lab A1 mini", 180)]
)
def test_a1_project_preserves_slot_and_uses_single_tool_volume(tmp_path, machine, size):
    profile = read_project(
        project_file(
            tmp_path,
            printer_model=machine,
            nozzle_diameter=["0.4"],
            printable_area=["0x0", f"{size}x0", f"{size}x{size}", f"0x{size}"],
            printable_height=str(size),
            extruder_printable_area=[],
            extruder_printable_height=[],
        )
    )
    assert profile["filament_slot"] == 2
    assert profile["bed_mm"] == [size, size, size]


@pytest.mark.parametrize(
    "change", [{"printable_height": "300"}, {"nozzle_diameter": ["0.6"]}]
)
def test_a1_invalid_configuration_is_rejected(tmp_path, change):
    settings = dict(
        printer_model="Bambu Lab A1",
        nozzle_diameter=["0.4"],
        printable_area=["0x0", "256x0", "256x256", "0x256"],
        printable_height="256",
    )
    settings.update(change)
    with pytest.raises(ValueError):
        read_project(project_file(tmp_path, **settings))


@pytest.mark.parametrize(
    "change",
    [
        {"printer_model": "Bambu Lab X1 Carbon"},
        {"nozzle_diameter": ["0.4", "0.6"]},
        {"post_process": ["unsafe-command"]},
        {"filament_type": ["PETG"]},
        {"extruder_printable_height": []},
    ],
)
def test_incompatible_project_is_not_silently_substituted(tmp_path, change):
    with pytest.raises(ValueError):
        read_project(project_file(tmp_path, **change))


def test_generated_project_only_contains_new_geometry_and_settings(tmp_path):
    profile = read_project(project_file(tmp_path))
    mesh = tmp_path / "new.stl"
    trimesh.creation.box(extents=[3, 2, 1]).export(mesh)
    target = tmp_path / "quote.3mf"
    write_project(profile, mesh, "cm", target)
    with ZipFile(target) as z:
        assert "Auxiliaries/private.txt" not in z.namelist()
        assert b"original-private-model" not in z.read("Metadata/model_settings.config")
        assert (
            json.loads(z.read("Metadata/project_settings.config"))
            == profile["settings"]
        )
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        vertices = root.findall(".//{" + CORE + "}vertex")
        dimensions = [
            max(float(v.get(axis)) for v in vertices)
            - min(float(v.get(axis)) for v in vertices)
            for axis in ("x", "y", "z")
        ]
        assert dimensions == [30, 20, 10]
        assert len(root.findall(".//{" + CORE + "}triangle")) == 12
    reread = read_project(target)
    assert reread["filament_slot"] == 2


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SLICER") != "1", reason="Opt-in native X2D profile integration"
)
def test_native_x2d_quote_and_local_reservation(client):
    from backend import integrations

    if not any(
        p["id"] == "x2d-pla-0.4-v1" and p["available"]
        for p in integrations.public_profiles()
    ):
        pytest.skip("Local operator-provided X2D profile is not installed")
    key = job(client)
    r = client.post(
        f"/api/jobs/{key}/slice-quotes",
        json={
            "profile_id": "x2d-pla-0.4-v1",
            "confirmed": True,
            "idempotency_key": "real-x2d-profile-test",
        },
    )
    assert r.status_code == 202, r.text
    task = client.get("/api/tasks/" + r.json()["id"]).json()
    assert task["status"] == "succeeded", task
    report = client.get("/api/tasks/" + task["id"] + "/report").json()
    plate = report["sliced_plates"][0]
    assert plate["triangle_count"] == 12
    assert plate["filaments"][0]["id"] == 2
    assert plate["filament_change_times"] == 0
    q = next(
        q
        for q in client.get("/api/state").json()["quotes"]
        if q["id"] == task["quote_id"]
    )
    _, configs, _ = integrations.load_profile("x2d-pla-0.4-v1")
    assert q["slicer"]["settings"]["infill_percent"] == float(
        configs["process"]["sparse_infill_density"].rstrip("%")
    )
    assert q["slicer"]["settings"]["supports"] == (
        str(configs["process"]["enable_support"]) == "1"
    )
    assert q["slicer"]["from_project"] is True
    p = plan(client, key)
    assert p["choice"]["printer_id"] == "bambu-x2d"
    assert not p["alternatives"]  # A1 reference printers cannot inherit X2D durations.
    assert approve(client, p).status_code == 200
