"""Read a Bambu settings project as data; generate new projects with fresh geometry.

The original model, thumbnails, author metadata, and any existing sliced files are
never carried into quotes. The original filament-slot/tool mapping is retained.
"""

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import trimesh

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ET.register_namespace("", CORE)


def read_project(path: Path):
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
            raise ValueError("Project archive exceeds inspection limits.")

        def read(name):
            info = archive.getinfo(name)
            if info.file_size > 4 * 1024 * 1024:
                raise ValueError("Project settings exceed inspection limits.")
            return archive.read(name)

        settings = json.loads(read("Metadata/project_settings.config"))
        xml = read("Metadata/model_settings.config")
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("XML declarations are not permitted in profile settings.")
        model = ET.fromstring(xml)
    if settings.get("printer_model") != "Bambu Lab X2D":
        raise ValueError("The project must contain the Bambu Lab X2D machine profile.")
    if settings.get("post_process"):
        raise ValueError("Post-processing scripts are not permitted.")
    nozzles = settings.get("nozzle_diameter", [])
    if nozzles != ["0.4", "0.4"]:
        raise ValueError("This X2D adapter is validated only for two 0.4 mm nozzles.")
    filaments = settings.get("filament_type", [])
    if not filaments or any(f != "PLA" for f in filaments):
        raise ValueError("Only PLA projects are supported.")
    objects = model.findall("object")
    if len(objects) != 1 or len(objects[0].findall("part")) != 1:
        raise ValueError(
            "Use a single-part project without modifiers for profile onboarding."
        )
    obj = objects[0]
    part = obj.find("part")
    if part.get("subtype", "normal_part") != "normal_part":
        raise ValueError("Modifiers are unsupported.")
    ignored = {
        "name",
        "extruder",
        "matrix",
        "source_file",
        "source_object_id",
        "source_volume_id",
        "source_offset_x",
        "source_offset_y",
        "source_offset_z",
        "thumbnail_file",
    }
    for node in [obj, part]:
        if any(
            m.get("key") and m.get("key") not in ignored
            for m in node.findall("metadata")
        ):
            raise ValueError(
                "Object-specific manufacturing overrides require manual profile review."
            )
    values = [
        m.get("value")
        for node in [obj, part]
        for m in node.findall("metadata")
        if m.get("key") == "extruder"
    ]
    if not values or len(set(values)) != 1:
        raise ValueError("A single unambiguous filament-slot assignment is required.")
    slot = int(values[0])
    if not 1 <= slot <= len(filaments):
        raise ValueError("Invalid filament-slot assignment.")
    plates = model.findall("plate")
    if len(plates) != 1:
        raise ValueError("Use a single-plate project.")
    plate_mapping = {
        m.get("key"): m.get("value")
        for m in plates[0].findall("metadata")
        if m.get("key")
        in ("filament_map_mode", "filament_maps", "filament_volume_maps")
    }
    if not plate_mapping.get("filament_maps"):
        raise ValueError("Missing plate tool mapping.")
    # Use the intersection of both tool envelopes. Bambu additionally validates the
    # actual placement, exclusion zones, support, and skirt during each slice.
    regions = settings.get("extruder_printable_area", [])
    heights = [float(x) for x in settings.get("extruder_printable_height", [])]
    if len(regions) != 2 or len(heights) != 2:
        raise ValueError("Missing X2D per-tool build envelopes.")
    boxes = []
    for region in regions:
        pts = [tuple(float(v) for v in pair.split("x")) for pair in region.split(",")]
        xs, ys = zip(*pts)
        box = (min(xs), min(ys), max(xs), max(ys))
        if set(pts) != {
            (box[0], box[1]),
            (box[0], box[3]),
            (box[2], box[1]),
            (box[2], box[3]),
        }:
            raise ValueError("Only rectangular tool envelopes are supported.")
        boxes.append(box)
    bed = [
        min(b[2] for b in boxes) - max(b[0] for b in boxes),
        min(b[3] for b in boxes) - max(b[1] for b in boxes),
        min(heights),
    ]
    if min(bed) <= 0:
        raise ValueError("Tool envelopes have no valid common volume.")
    return {
        "settings": settings,
        "filament_slot": slot,
        "plate_mapping": plate_mapping,
        "bed_mm": bed,
    }


def project_fingerprint(project):
    return hashlib.sha256(json.dumps(project, sort_keys=True).encode()).hexdigest()


def write_project(project, mesh_path: Path, units: str, target: Path):
    mesh = trimesh.load(mesh_path, file_type="stl", force="mesh")
    mesh.apply_scale({"mm": 1, "cm": 10, "in": 25.4}[units])
    mesh.vertices[:, 0] -= mesh.bounds[:, 0].mean()
    mesh.vertices[:, 1] -= mesh.bounds[:, 1].mean()
    mesh.vertices[:, 2] -= mesh.bounds[0, 2]

    def tag(name):
        return "{" + CORE + "}" + name

    root = ET.Element(tag("model"), {"unit": "millimeter"})
    ET.SubElement(
        root, tag("metadata"), {"name": "Application"}
    ).text = "BambuStudio-02.08.02.61"
    ET.SubElement(root, tag("metadata"), {"name": "BambuStudio:3mfVersion"}).text = "1"
    resources = ET.SubElement(root, tag("resources"))
    obj = ET.SubElement(resources, tag("object"), {"id": "1", "type": "model"})
    geometry = ET.SubElement(obj, tag("mesh"))
    vertices = ET.SubElement(geometry, tag("vertices"))
    faces = ET.SubElement(geometry, tag("triangles"))
    for x, y, z in mesh.vertices:
        ET.SubElement(vertices, tag("vertex"), {"x": str(x), "y": str(y), "z": str(z)})
    for a, b, c in mesh.faces:
        ET.SubElement(
            faces, tag("triangle"), {"v1": str(a), "v2": str(b), "v3": str(c)}
        )
    group = ET.SubElement(resources, tag("object"), {"id": "2", "type": "model"})
    ET.SubElement(
        ET.SubElement(group, tag("components")), tag("component"), {"objectid": "1"}
    )
    ET.SubElement(
        ET.SubElement(root, tag("build")),
        tag("item"),
        {"objectid": "2", "transform": "1 0 0 0 1 0 0 0 1 128 128 0", "printable": "1"},
    )
    config = ET.Element("config")
    obj = ET.SubElement(config, "object", {"id": "2"})
    ET.SubElement(obj, "metadata", {"key": "name", "value": "quote-part.stl"})
    ET.SubElement(
        obj, "metadata", {"key": "extruder", "value": str(project["filament_slot"])}
    )
    ET.SubElement(obj, "part", {"id": "1", "subtype": "normal_part"})
    plate = ET.SubElement(config, "plate")
    ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
    for key, value in project["plate_mapping"].items():
        ET.SubElement(plate, "metadata", {"key": key, "value": value})
    inst = ET.SubElement(plate, "model_instance")
    ET.SubElement(inst, "metadata", {"key": "object_id", "value": "2"})
    ET.SubElement(inst, "metadata", {"key": "instance_id", "value": "0"})
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        )
        archive.writestr(
            "3D/3dmodel.model",
            ET.tostring(root, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "Metadata/model_settings.config",
            ET.tostring(config, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "Metadata/project_settings.config", json.dumps(project["settings"])
        )
