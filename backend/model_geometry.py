"""Pure model inspection, invoked only in the limited worker outside unit tests."""

import hashlib
import io
from pathlib import Path

import numpy as np
import trimesh

from backend import mesh_upload
from backend.model_limits import MAX_NORMALIZED_BYTES


def inspect(content, filename, repair=False):
    extension = Path(filename).suffix.lower()
    if extension == ".3mf":
        mesh = mesh_upload.import_3mf(content)
    elif extension == ".stl":
        mesh = trimesh.load(io.BytesIO(content), file_type="stl", force="mesh")
    else:
        raise mesh_upload.MeshImportError("Only STL and 3MF files are supported")
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise mesh_upload.MeshImportError("Model contains no valid finite geometry.")
    if len(mesh.faces) > mesh_upload.MAX_TRIANGLES:
        raise mesh_upload.MeshImportError(
            f"Model contains {len(mesh.faces):,} triangles; limit is {mesh_upload.MAX_TRIANGLES:,}. Export a simplified model."
        )
    if repair:
        raise mesh_upload.MeshImportError(
            "Automatic repair is no longer available. Upload a repaired model from an external tool."
        )
    if not repair and (not mesh.is_watertight or abs(mesh.volume) <= 0):
        raise mesh_upload.MeshImportError(
            "Model is not a closed watertight solid. Repair the mesh before uploading."
        )
    dims = mesh.extents.tolist()
    if min(dims) <= 0:
        raise mesh_upload.MeshImportError("Mesh must have positive dimensions.")
    # Always emit bounded binary STL, including for ASCII STL sources.
    normalized = mesh.export(file_type="stl")
    if len(normalized) > MAX_NORMALIZED_BYTES:
        raise mesh_upload.MeshImportError(
            "Normalized model exceeds the processing limit."
        )
    metadata = dict(
        sha256=hashlib.sha256(normalized).hexdigest(),
        filename=Path(filename).name,
        dimensions_native=dims,
        triangles=len(mesh.faces),
        watertight=bool(mesh.is_watertight),
        source_format=extension[1:],
        color_info=mesh.metadata.get("color_info") if extension == ".3mf" else None,
        source_sha256=hashlib.sha256(content).hexdigest(),
        embedded_units=mesh.metadata.get("embedded_units")
        if extension == ".3mf"
        else None,
        import_note="3MF geometry normalized to mm; embedded print settings ignored; quantity counts complete assemblies"
        if extension == ".3mf"
        else "STL units require operator confirmation",
    )
    return metadata, normalized, None
