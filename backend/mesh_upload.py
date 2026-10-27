"""Bounded 3MF geometry import. Embedded slicer settings are never executed."""

import io
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
import trimesh

from backend.model_limits import (
    MAX_TRIANGLES,
    MAX_ARCHIVE_BYTES,
    MAX_PART_BYTES,
    MAX_VERTICES,
)


class MeshImportError(ValueError):
    """Safe, specific validation detail for an uploaded model."""


CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
UNITS = {
    "micron": 0.001,
    "millimeter": 1,
    "centimeter": 10,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000,
}


def import_3mf(content):
    def xml(data):
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise MeshImportError("XML declarations are unsupported")
        return ET.fromstring(data)

    with ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
            raise MeshImportError("3MF archive exceeds limits")
        names = {i.filename for i in infos}
        if len(names) != len(infos) or any(i.flag_bits & 1 for i in infos):
            raise MeshImportError("Duplicate or encrypted archive entries")

        def read(name):
            if name not in names or archive.getinfo(name).file_size > MAX_PART_BYTES:
                raise MeshImportError("Missing or oversized 3MF part")
            return archive.read(name)

        rels = xml(read("_rels/.rels"))
        targets = [
            r.get("Target")
            for r in rels
            if r.get("Type", "").endswith("/3dmodel")
            and r.get("TargetMode", "Internal") == "Internal"
        ]
        if len(targets) != 1:
            raise MeshImportError("One internal 3MF model is required")

        def path(value):
            result = posixpath.normpath(value.lstrip("/"))
            if result.startswith("../") or ":" in result or "\\" in result:
                raise MeshImportError("External references unsupported")
            return result

        root_path = path(targets[0])
        settings = None
        if "Metadata/model_settings.config" in names:
            settings = xml(read("Metadata/model_settings.config"))
            if any(
                p.get("subtype", "normal_part") != "normal_part"
                for p in settings.findall(".//part")
            ):
                raise MeshImportError("3MF modifiers require manual review")
        from backend.color_inspection import ColorInspection

        color_inspector = ColorInspection(read, names, root_path, settings)
        docs = {}
        meshes = []
        triangles = 0

        def document(name):
            if name not in docs:
                root = xml(read(name))
                if root.tag != "{" + CORE + "}model":
                    raise MeshImportError("Unsupported 3MF model schema")
                scale = UNITS.get(root.get("unit", "millimeter"))
                if scale is None:
                    raise MeshImportError("Unsupported units")
                resources = root.find("{" + CORE + "}resources")
                if resources is None:
                    raise MeshImportError("Missing resources")
                color_inspector.document(name, resources)
                docs[name] = (
                    root,
                    scale,
                    {
                        o.get("id"): o
                        for o in resources
                        if o.tag == "{" + CORE + "}object"
                    },
                )
            return docs[name]

        def transform(raw, scale):
            t = np.eye(4)
            if raw:
                values = np.array([float(v) for v in raw.split()])
                if len(values) != 12 or not np.isfinite(values).all():
                    raise MeshImportError("Invalid transform")
                t[:3, :] = values.reshape(4, 3).T
                t[:3, 3] *= scale
            return t

        def visit(name, oid, matrix, stack):
            nonlocal triangles
            key = (name, oid)
            if key in stack or len(stack) > 20:
                raise MeshImportError("Cyclic or excessive assembly")
            _, scale, objects = document(name)
            obj = objects[oid]
            if obj.get("type", "model") != "model":
                raise MeshImportError("Unsupported object type")
            geometry = obj.find("{" + CORE + "}mesh")
            if geometry is not None:
                faces = geometry.findall(
                    "{" + CORE + "}triangles/{" + CORE + "}triangle"
                )
                color_inspector.object(name, obj, faces)
                triangles += len(faces)
                if triangles > MAX_TRIANGLES:
                    raise MeshImportError(
                        f"Model contains {triangles:,} triangles; limit is {MAX_TRIANGLES:,}. Export a simplified model before uploading."
                    )
                vertices = geometry.findall(
                    "{" + CORE + "}vertices/{" + CORE + "}vertex"
                )
                if len(vertices) > MAX_VERTICES:
                    raise MeshImportError("Geometry exceeds vertex limit")
                verts = (
                    np.array(
                        [[float(v.get(a)) for a in ("x", "y", "z")] for v in vertices]
                    )
                    * scale
                )
                indices = np.array(
                    [[int(f.get(a)) for a in ("v1", "v2", "v3")] for f in faces]
                )
                if not len(indices) or indices.min() < 0 or indices.max() >= len(verts):
                    raise MeshImportError("Invalid triangles")
                mesh = trimesh.Trimesh(vertices=verts, faces=indices, process=True)
                mesh.apply_transform(matrix)
                meshes.append(mesh)
            else:
                color_inspector.object(name, obj, [])
                components = obj.findall(
                    "{" + CORE + "}components/{" + CORE + "}component"
                )
                if not components:
                    raise MeshImportError("Empty object")
                for component in components:
                    ref = next(
                        (v for k, v in component.attrib.items() if k.endswith("}path")),
                        name,
                    )
                    visit(
                        path(ref),
                        component.get("objectid"),
                        matrix @ transform(component.get("transform"), scale),
                        stack + (key,),
                    )

        root, scale, _ = document(root_path)
        items = root.findall("{" + CORE + "}build/{" + CORE + "}item")
        if not items:
            raise MeshImportError("Empty build")
        for item in items:
            if item.get("printable", "1") not in ("0", "false"):
                visit(
                    root_path,
                    item.get("objectid"),
                    transform(item.get("transform"), scale),
                    (),
                )
        if not meshes:
            raise MeshImportError("No printable geometry")
        # One uploaded assembly is one quoted unit; preserve relative placement.
        result = trimesh.util.concatenate(meshes)
        result.metadata["color_info"] = color_inspector.summary()
        result.metadata["embedded_units"] = root.get("unit", "millimeter")
        return result
