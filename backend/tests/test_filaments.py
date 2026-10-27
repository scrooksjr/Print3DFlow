from datetime import datetime, timedelta, timezone
import pytest
import trimesh


@pytest.mark.parametrize("material", ["PETG", "ABS", "ASA", "TPU"])
def test_requested_material_is_recorded_but_cannot_use_pla_quotes(client, material):
    staged = client.post(
        "/api/model-uploads",
        files={"file": ("box.stl", trimesh.creation.box().export(file_type="stl"))},
    ).json()
    r = client.post(
        "/api/jobs",
        json=dict(
            title=material + " request",
            request="Three prints in " + material,
            quantity=3,
            units="mm",
            material=material,
            color="black",
            deadline=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            model_upload_id=staged["id"],
        ),
    )
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["material"] == material and j["status"] == "awaiting_material_profile"
    assert (
        client.post(
            "/api/jobs/" + j["id"] + "/quotes",
            json=dict(confirmed=True, grams_per_part=5, hours_per_part=1),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/jobs/" + j["id"] + "/slice-quotes",
            json=dict(
                confirmed=True,
                profile_id="demo-pla-0.2-v1",
                idempotency_key="material-slice-" + material,
            ),
        ).status_code
        == 422
    )
    assert not client.get("/api/state").json()["quotes"]
    assert not client.get("/api/state").json()["reservations"]


def test_catalog_does_not_invent_configured_profiles(client):
    result = client.get("/api/filaments").json()["materials"]
    assert {m["material"] for m in result} == {"PLA", "PETG", "ABS", "ASA", "TPU"}
    for item in result:
        if item["material"] != "PLA":
            assert not item["quoting_enabled"] and not item["profile_ids"]
            assert item["required"]
