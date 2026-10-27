"""Bounded 3MF geometry import. Embedded slicer settings are never executed."""

import io
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
import trimesh

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
            raise ValueError("XML declarations are unsupported")
        return ET.fromstring(data)

    with ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or sum(i.file_size for i in infos) > 64 * 1024 * 1024:
            raise ValueError("3MF archive exceeds limits")
        names = {i.filename for i in infos}
        if len(names) != len(infos) or any(i.flag_bits & 1 for i in infos):
            raise ValueError("Duplicate or encrypted archive entries")

        def read(name):
            if name not in names or archive.getinfo(name).file_size > 24 * 1024 * 1024:
                raise ValueError("Missing or oversized 3MF part")
            return archive.read(name)

        rels = xml(read("_rels/.rels"))
        targets = [
            r.get("Target")
            for r in rels
            if r.get("Type", "").endswith("/3dmodel")
            and r.get("TargetMode", "Internal") == "Internal"
        ]
        if len(targets) != 1:
            raise ValueError("One internal 3MF model is required")

        def path(value):
            result = posixpath.normpath(value.lstrip("/"))
            if result.startswith("../") or ":" in result or "\\" in result:
                raise ValueError("External references unsupported")
            return result

        root_path = path(targets[0])
        if "Metadata/model_settings.config" in names:
            settings = xml(read("Metadata/model_settings.config"))
            if any(
                p.get("subtype", "normal_part") != "normal_part"
                for p in settings.findall(".//part")
            ):
                raise ValueError("3MF modifiers require manual review")
        docs = {}
        meshes = []
        triangles = 0

        def document(name):
            if name not in docs:
                root = xml(read(name))
                if root.tag != "{" + CORE + "}model":
                    raise ValueError("Unsupported 3MF model schema")
                scale = UNITS.get(root.get("unit", "millimeter"))
                if scale is None:
                    raise ValueError("Unsupported units")
                resources = root.find("{" + CORE + "}resources")
                if resources is None:
                    raise ValueError("Missing resources")
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
                    raise ValueError("Invalid transform")
                t[:3, :] = values.reshape(4, 3).T
                t[:3, 3] *= scale
            return t

        def visit(name, oid, matrix, stack):
            nonlocal triangles
            key = (name, oid)
            if key in stack or len(stack) > 20:
                raise ValueError("Cyclic or excessive assembly")
            _, scale, objects = document(name)
            obj = objects[oid]
            if obj.get("type", "model") != "model":
                raise ValueError("Unsupported object type")
            geometry = obj.find("{" + CORE + "}mesh")
            if geometry is not None:
                faces = geometry.findall(
                    "{" + CORE + "}triangles/{" + CORE + "}triangle"
                )
                triangles += len(faces)
                if triangles > 100000:
                    raise ValueError("Geometry exceeds triangle limit")
                vertices = geometry.findall(
                    "{" + CORE + "}vertices/{" + CORE + "}vertex"
                )
                if len(vertices) > 300000:
                    raise ValueError("Geometry exceeds vertex limit")
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
                    raise ValueError("Invalid triangles")
                mesh = trimesh.Trimesh(vertices=verts, faces=indices, process=True)
                mesh.apply_transform(matrix)
                meshes.append(mesh)
            else:
                components = obj.findall(
                    "{" + CORE + "}components/{" + CORE + "}component"
                )
                if not components:
                    raise ValueError("Empty object")
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
            raise ValueError("Empty build")
        for item in items:
            if item.get("printable", "1") not in ("0", "false"):
                visit(
                    root_path,
                    item.get("objectid"),
                    transform(item.get("transform"), scale),
                    (),
                )
        if not meshes:
            raise ValueError("No printable geometry")
        # One uploaded assembly is one quoted unit; preserve relative placement.
        result = trimesh.util.concatenate(meshes)
        result.metadata["embedded_units"] = root.get("unit", "millimeter")
        return result
