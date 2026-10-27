"""Conservative repair of a copy; no rescaling, remeshing, or large-hole closure."""

import io

import numpy as np
import trimesh

from backend.mesh_upload import MeshImportError
from backend.model_limits import MAX_REPAIR_TRIANGLES


def repair_copy(content):
    mesh = trimesh.load(io.BytesIO(content), file_type="stl", force="mesh")
    if len(mesh.faces) > MAX_REPAIR_TRIANGLES:
        raise MeshImportError(
            "Automatic repair is limited to 250,000 triangles; repair larger models externally."
        )
    original = mesh.copy()

    def metrics(m):
        return dict(
            triangles=len(m.faces),
            watertight=bool(m.is_watertight),
            dimensions_mm_or_native=m.extents.tolist(),
            volume_signed=float(m.volume),
        )

    before = metrics(mesh)
    mask = mesh.nondegenerate_faces() & mesh.unique_faces()
    removed = int((~mask).sum())
    mesh.update_faces(mask)
    mesh.remove_unreferenced_vertices()
    boundary = int((np.bincount(mesh.edges_unique_inverse) == 1).sum())
    if boundary > 1000:
        raise MeshImportError(
            "Automatic repair declined: too many boundary edges. Repair the model in a dedicated mesh editor and upload again."
        )
    count = len(mesh.faces)
    trimesh.repair.fill_holes(mesh)
    added = len(mesh.faces) - count
    trimesh.repair.fix_normals(mesh, multibody=True)
    if not mesh.is_volume or len(mesh.faces) > MAX_REPAIR_TRIANGLES:
        raise MeshImportError(
            "Automatic repair could not produce a closed valid solid. No model was replaced. Use a dedicated mesh repair tool and upload the repaired file."
        )
    if not np.allclose(mesh.bounds, original.bounds, atol=1e-5, rtol=0):
        raise MeshImportError(
            "Repair changed the model envelope; manual review in a mesh editor is required."
        )
    repaired = mesh.export(file_type="stl")
    persisted = trimesh.load(io.BytesIO(repaired), file_type="stl", force="mesh")
    if not persisted.is_volume:
        raise MeshImportError(
            "Repaired geometry failed validation after export. Original unchanged; use a dedicated mesh repair tool."
        )
    return repaired, dict(
        before=before,
        after=metrics(mesh),
        removed_faces=removed,
        added_faces=added,
        operations=[
            "Remove degenerate/duplicate triangles",
            "Fill small triangular or quadrilateral holes",
            "Correct face winding",
        ],
        warning="Topology and surfaces may change even when dimensions match. Inspect the downloaded repaired model before approving. No scale change is applied.",
    )
