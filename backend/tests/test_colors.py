import copy
import io
import json
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from backend.mesh_upload import CORE, import_3mf
from backend.tests.test_mesh_upload import model_file


def color_project(colors=4, core=False, paint=False, slots=(2,)):
    with ZipFile(io.BytesIO(model_file())) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = ET.fromstring(parts["3D/3dmodel.model"])

    def tag(n):
        return "{" + CORE + "}" + n

    resources = root.find(tag("resources"))
    obj = resources.find(tag("object"))
    palette = ["#FF0000", "#00FF00", "#0000FF", "#FFFFFF", "#FFFF00"][:colors]
    if core:
        group = ET.SubElement(
            resources,
            "{http://schemas.microsoft.com/3dmanufacturing/material/2015/02}colorgroup",
            {"id": "10"},
        )
        for color in palette:
            ET.SubElement(
                group,
                "{http://schemas.microsoft.com/3dmanufacturing/material/2015/02}color",
                {"color": color},
            )
        obj.set("pid", "10")
        obj.set("pindex", "0")
        for i, t in enumerate(root.findall(".//" + tag("triangle"))):
            t.set("p1", str(i % colors))
    if paint:
        root.find(".//" + tag("triangle")).set(
            "paint_color", "opaque-vendor-paint-data"
        )
    if len(slots) > 1:
        for i in range(2, len(slots) + 1):
            clone = copy.deepcopy(obj)
            clone.set("id", str(i))
            resources.append(clone)
        assembly = ET.SubElement(resources, tag("object"), {"id": "20"})
        children = ET.SubElement(assembly, tag("components"))
        for i in range(len(slots)):
            ET.SubElement(
                children,
                tag("component"),
                {
                    "objectid": str(i + 1),
                    "transform": f"1 0 0 0 1 0 0 0 1 {i * 10} 0 0",
                },
            )
        root.find(tag("build") + "/" + tag("item")).set("objectid", "20")
        config = (
            '<config><object id="20">'
            + "".join(
                f'<part id="{i + 1}" subtype="normal_part"><metadata key="extruder" value="{slot}"/></part>'
                for i, slot in enumerate(slots)
            )
            + "</object></config>"
        )
    else:
        config = (
            f'<config><object id="1"><metadata key="extruder" value="{slots[0]}"/><part id="1" subtype="normal_part"/></object></config>'
            if slots
            else "<config/>"
        )
    parts["Metadata/model_settings.config"] = config.encode()
    parts["Metadata/project_settings.config"] = json.dumps(
        dict(filament_colour=palette, filament_type=["PLA"] * colors)
    ).encode()
    parts["3D/3dmodel.model"] = ET.tostring(root)
    out = io.BytesIO()
    with ZipFile(out, "w") as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return out.getvalue()


def test_saved_slots_are_not_all_assumed_used():
    info = import_3mf(color_project()).metadata["color_info"]
    assert len(info["saved_filaments"]) == 4
    assert info["assigned_slots"] == [2]
    assert not info["multicolor_detected"] and not info["quoting_blocked"]


def test_four_used_slots_detected_and_blocked():
    info = import_3mf(color_project(slots=(1, 2, 3, 4))).metadata["color_info"]
    assert info["assigned_slots"] == [1, 2, 3, 4] and info["multicolor_detected"]
    assert info["max_supported_colors"] == 4 and not info["exceeds_mvp_limit"]
    assert (
        info["quoting_blocked"]
        and not info["mappings_verified"]
        and not info["slicer_results_verified"]
    )


def test_standard_face_colors_and_more_than_four_limit():
    for count in (4, 5):
        info = import_3mf(color_project(colors=count, core=True, slots=())).metadata[
            "color_info"
        ]
        assert info["assigned_color_count"] == count
        assert info["multicolor_detected"] and info["quoting_blocked"]
        assert info["exceeds_mvp_limit"] == (count > 4)


def test_encoded_paint_and_unassigned_palette_require_review():
    for data in (color_project(paint=True), color_project(slots=())):
        assert import_3mf(data).metadata["color_info"]["quoting_blocked"]


def test_vendor_object_color_is_not_silently_discarded():
    with ZipFile(io.BytesIO(color_project())) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = ET.fromstring(parts["3D/3dmodel.model"])
    root.find(".//{" + CORE + "}object").set("paint_color", "vendor-encoded")
    parts["3D/3dmodel.model"] = ET.tostring(root)
    out = io.BytesIO()
    with ZipFile(out, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    info = import_3mf(out.getvalue()).metadata["color_info"]
    assert info["painted_faces_detected"] and info["quoting_blocked"]


def test_all_quote_routes_block_multicolor_before_slicing(client, monkeypatch):
    from backend import integrations

    def should_not_run(*args, **kwargs):
        raise AssertionError("Multicolor cannot reach the slicer")

    monkeypatch.setattr(integrations, "run_bambu_slice", should_not_run)
    staged = client.post(
        "/api/model-uploads",
        files={"file": ("four-colors.3mf", color_project(slots=(1, 2, 3, 4)))},
    ).json()
    assert staged["file"]["color_info"]["quoting_blocked"]
    r = client.post(
        "/api/jobs",
        json=dict(
            title="Four color model",
            quantity=1,
            material="PLA",
            units="mm",
            model_upload_id=staged["id"],
            deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        ),
    )
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    for endpoint, body in [
        ("quotes", dict(confirmed=True, grams_per_part=10, hours_per_part=1)),
        (
            "slice-quotes",
            dict(
                confirmed=True,
                profile_id="demo-pla-0.2-v1",
                idempotency_key="blocked-multicolor-slice",
            ),
        ),
        ("comparisons", dict(confirmed=True, profile_ids=["a1-pla-0.4-v1"])),
    ]:
        response = client.post("/api/jobs/" + jid + "/" + endpoint, json=body)
        assert response.status_code == 422, response.text
    assert not client.get("/api/state").json()["quotes"]
    assert not client.get("/api/state").json()["reservations"]


def test_legacy_3mf_without_color_inspection_requires_reupload(client):
    from backend import main as m
    from backend.tests.test_workflow import job

    jid = job(client)
    with m.transaction() as c:
        j = m.get(c, jid, "job")
        j["file"]["source_format"] = "3mf"
        j["file"].pop("color_info", None)
        m.put(c, "job", j)
    r = client.post(
        "/api/jobs/" + jid + "/quotes",
        json=dict(confirmed=True, grams_per_part=1, hours_per_part=0.1),
    )
    assert r.status_code == 422 and "Re-upload" in r.json()["detail"]


def test_real_worker_preserves_four_color_metadata(tmp_path):
    from backend.model_processing import execute_worker

    (tmp_path / "input.model").write_bytes(color_project(slots=(1, 2, 3, 4)))
    (tmp_path / "request.json").write_text(
        json.dumps(dict(filename="four-colors.3mf", repair=False))
    )
    metadata, normalized, _ = execute_worker(tmp_path)
    assert metadata["color_info"]["assigned_slots"] == [1, 2, 3, 4]
    assert metadata["color_info"]["quoting_blocked"]
    assert metadata["preview_sha256"]
    assert (tmp_path / "preview.glb").read_bytes().startswith(b"glTF")
    assert not normalized.startswith(b"PK")


def test_assigned_shades_use_readable_names_without_changing_exact_colors():
    from backend.color_inspection import infer_colors

    shades = ["#161616FF", "#FFFFFFFF", "#FFF144FF", "#0ACC38FF"]
    info = dict(saved_filaments=[dict(slot=i + 1, color=c) for i, c in enumerate(shades)],
                assigned_slots=[1, 2, 3, 4], assignments=[], block_reasons=[])
    result = infer_colors(info)
    assert result["suggested_color"] == "Black / White / Yellow / Green"
    assert [c["color"] for c in result["assigned_colors"]] == shades
    info["assigned_slots"] = [4]
    assert infer_colors(info)["suggested_color"] == "Green"
    info["painted_faces_detected"] = True
    assert infer_colors(info)["suggested_color"] is None


def test_color_name_handles_shades_and_opacity():
    from backend.color_inspection import color_name

    for code, name in {"#FFE000FF": "Yellow", "#75B52AFF": "Green",
                       "#808080FF": "Gray", "#FFA500FF": "Orange",
                       "#800080FF": "Purple", "#0000FF80": "Transparent Blue"}.items():
        assert color_name(code) == name


def test_component_preview_preserves_color_and_geometry_and_quote_block():
    mesh = import_3mf(color_project(slots=(1, 2, 3, 4)))
    import trimesh
    scene = trimesh.load(io.BytesIO(mesh.metadata["preview_glb"]), file_type="glb")
    geometry = scene.to_geometry()
    assert len(geometry.faces) == len(mesh.faces)
    assert set(map(tuple, geometry.visual.vertex_colors)) == {
        (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)}
    assert mesh.metadata["color_info"]["quoting_blocked"]
    for data in (color_project(paint=True), color_project(slots=())):
        assert "preview_glb" not in import_3mf(data).metadata


def test_preview_is_stored_separately_and_served_without_enabling_quotes(client):
    staged = client.post('/api/model-uploads', files={'file':('colored.3mf',color_project(slots=(1,2,3,4)))}).json()
    jid = client.post('/api/jobs',json=dict(title='Color preview',quantity=1,material='PLA',units='mm',model_upload_id=staged['id'],deadline=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat())).json()['id']
    preview = client.get('/api/jobs/'+jid+'/preview')
    assert preview.status_code == 200 and preview.content.startswith(b'glTF')
    assert client.get('/api/jobs/'+jid+'/mesh').content[:4] != b'glTF'
    assert client.post('/api/jobs/'+jid+'/quotes',json=dict(confirmed=True,grams_per_part=1,hours_per_part=1)).status_code == 422


def test_custom_finish_is_recorded_but_cannot_be_quoted_as_print_only(client):
    staged = client.post('/api/model-uploads',files={'file':('single.3mf',color_project())}).json()
    j = client.post('/api/jobs',json=dict(title='Painted request',quantity=1,material='PLA',finish='painting',units='mm',model_upload_id=staged['id'],deadline=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()))
    assert j.status_code == 201 and j.json()['finish'] == 'painting'
    jid = j.json()['id']
    for ep,body in [('quotes',dict(confirmed=True,grams_per_part=1,hours_per_part=1)),('slice-quotes',dict(confirmed=True,profile_id='a1mini-pla-0.4-v1',idempotency_key='finish-block')),('comparisons',dict(confirmed=True,profile_ids=['a1-pla-0.4-v1']))]:
        r = client.post('/api/jobs/'+jid+'/'+ep,json=body)
        assert r.status_code == 422 and 'finishing' in r.text.lower()
