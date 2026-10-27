import io
from zipfile import ZipFile

import pytest

from backend.tests.test_workflow import job


def model_file(unit="millimeter", transform="1 0 0 0 1 0 0 0 1 10 20 0", cycle=False):
    import trimesh

    mesh = trimesh.creation.box(extents=[3, 2, 1])
    vertices = "".join(
        f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in mesh.vertices
    )
    faces = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
    obj = f"<mesh><vertices>{vertices}</vertices><triangles>{faces}</triangles></mesh>"
    if cycle:
        obj = '<components><component objectid="1"/></components>'
    content = io.BytesIO()
    with ZipFile(content, "w") as z:
        z.writestr(
            "_rels/.rels",
            '<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/3dmodel.model"/></Relationships>',
        )
        z.writestr(
            "3D/3dmodel.model",
            f'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="{unit}"><resources><object id="1">{obj}</object></resources><build><item objectid="1" transform="{transform}"/></build></model>',
        )
        z.writestr(
            "Metadata/project_settings.config",
            '{"post_process":["do-not-execute"],"printer_model":"untrusted"}',
        )
    return content.getvalue()


def test_3mf_normalizes_units_and_ignores_embedded_profiles(client):
    jid = job(client)
    response = client.post(
        f"/api/jobs/{jid}/file", files={"file": ("part.3mf", model_file("centimeter"))}
    )
    assert response.status_code == 200, response.text
    j = response.json()
    assert j["units"] == "mm"
    assert j["file"]["dimensions_native"] == [30, 20, 10]
    assert j["file"]["source_format"] == "3mf"
    assert client.get(f"/api/jobs/{jid}/mesh").content[:2] != b"PK"
    q = client.post(
        f"/api/jobs/{jid}/quotes",
        json=dict(confirmed=True, grams_per_part=1, hours_per_part=0.1),
    )
    assert q.status_code == 201, q.text
    assert q.json()["dimensions_mm"] == [30, 20, 10]


@pytest.mark.parametrize(
    "content", [b"not a zip", model_file(cycle=True), model_file(unit="unknown")]
)
def test_bad_3mf_does_not_change_job(client, content):
    jid = job(client)
    before = client.get("/api/state").json()["jobs"]
    assert (
        client.post(
            f"/api/jobs/{jid}/file", files={"file": ("bad.3mf", content)}
        ).status_code
        == 422
    )
    assert client.get("/api/state").json()["jobs"] == before
