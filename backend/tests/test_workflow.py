from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import trimesh


def job(client, deadline_hours=72, units="mm"):
    mesh = trimesh.creation.box(extents=[20, 30, 10]).export(file_type="stl")
    staged = client.post("/api/model-uploads", files={"file": ("box.stl", mesh)})
    assert staged.status_code == 201, staged.text
    res = client.post(
        "/api/jobs",
        json=dict(
            model_upload_id=staged.json()["id"],
            title="Fixture bracket",
            request="Three PLA parts",
            quantity=3,
            units=units,
            deadline=(
                datetime.now(timezone.utc) + timedelta(hours=deadline_hours)
            ).isoformat(),
        ),
    )
    assert res.status_code == 201, res.text
    j = res.json()
    mesh = trimesh.creation.box(extents=[20, 30, 10]).export(file_type="stl")
    assert (
        client.post(
            f"/api/jobs/{j['id']}/file", files={"file": ("box.stl", mesh)}
        ).status_code
        == 200
    )
    return j["id"]


def quoted(client, **kwargs):
    key = job(client, **kwargs)
    q = client.post(
        f"/api/jobs/{key}/quotes",
        json=dict(grams_per_part=25, hours_per_part=1.5, confirmed=True),
    )
    assert q.status_code == 201, q.text
    return key, q.json()


def plan(client, key):
    p = client.post(f"/api/jobs/{key}/proposals")
    assert p.status_code == 201, p.text
    return p.json()


def approve(client, p, key="approval-key-0001"):
    return client.post(
        f"/api/proposals/{p['id']}/approve", json={"idempotency_key": key}
    )


def test_quote_arithmetic_and_provenance(client):
    _, q = quoted(client)
    assert q["grams"] == 75 and q["hours"] == 4.5
    assert q["total_cents"] == 2220
    assert q["duration_minutes"] == 300
    assert q["source"] == "operator_entered_estimate"
    assert sum(i["cents"] for i in q["items"]) == q["total_cents"]


def test_missing_units_blocks_quote(client):
    key = job(client, units=None)
    assert (
        client.post(
            f"/api/jobs/{key}/quotes",
            json=dict(grams_per_part=25, hours_per_part=1, confirmed=True),
        ).status_code
        == 422
    )


def test_invalid_mesh_rejected(client):
    key = job(client)
    r = client.post(f"/api/jobs/{key}/file", files={"file": ("bad.stl", b"not a mesh")})
    assert r.status_code == 422


def test_quote_requires_confirmation(client):
    key = job(client)
    assert (
        client.post(
            f"/api/jobs/{key}/quotes",
            json=dict(grams_per_part=1, hours_per_part=1, confirmed=False),
        ).status_code
        == 422
    )


def test_reservation_and_idempotent_approval(client):
    key, _ = quoted(client)
    p = plan(client, key)
    r = approve(client, p)
    assert r.status_code == 200, r.text
    assert approve(client, p).json() == r.json()
    assert (
        len([r for r in client.get("/api/state").json()["reservations"] if r["active"]])
        == 1
    )


def test_recovery_preserves_old_until_approval(client):
    key, q = quoted(client)
    p = plan(client, key)
    r = approve(client, p).json()["reservation"]
    event = dict(
        printer_id=r["printer_id"],
        starts_at=datetime.now(timezone.utc).isoformat(),
        ends_at=(datetime.fromisoformat(r["end"]) + timedelta(hours=6)).isoformat(),
        reason="Simulated outage",
        event_key="outage-event-0001",
    )
    o = client.post("/api/outages", json=event)
    assert o.status_code == 201
    assert client.post("/api/outages", json=event).json()["id"] == o.json()["id"]
    state = client.get("/api/state").json()
    assert next(x for x in state["reservations"] if x["id"] == r["id"])["active"]
    recovery = client.post(f"/api/jobs/{key}/recovery").json()
    assert recovery["choice"]["printer_id"] != r["printer_id"]
    assert recovery["quote_id"] == q["id"]
    approved = approve(client, recovery, "approve-recovery-0001")
    assert approved.status_code == 200, approved.text
    state = client.get("/api/state").json()
    assert not next(x for x in state["reservations"] if x["id"] == r["id"])["active"]
    assert len([x for x in state["reservations"] if x["active"]]) == 1
    assert next(x for x in state["quotes"] if x["id"] == q["id"]) == q


def test_capacity_conflict_does_not_double_book(client):
    a, _ = quoted(client)
    b, _ = quoted(client)
    pa, pb = plan(client, a), plan(client, b)
    assert pa["choice"]["printer_id"] == pb["choice"]["printer_id"]
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda args: approve(client, *args),
                [(pa, "concurrent-aaaa"), (pb, "concurrent-bbbb")],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = b if results[1].status_code == 409 else a
    assert (
        approve(client, plan(client, loser), "retry-after-conflict").status_code == 200
    )


def test_outage_invalidates_existing_plan(client):
    key, _ = quoted(client)
    p = plan(client, key)
    client.post(
        "/api/outages",
        json=dict(
            printer_id=p["choice"]["printer_id"],
            starts_at=p["choice"]["start"],
            ends_at=p["choice"]["end"],
            reason="maintenance",
            event_key="outage-before-approve",
        ),
    )
    assert approve(client, p).status_code == 409
    assert not client.get("/api/state").json()["reservations"]


def test_late_plan_cannot_be_approved(client):
    key, _ = quoted(client, deadline_hours=1)
    p = plan(client, key)
    assert not p["choice"]["on_time"]
    assert approve(client, p).status_code == 409


def test_requote_invalidates_proposal(client):
    key, _ = quoted(client)
    p = plan(client, key)
    client.post(
        f"/api/jobs/{key}/quotes",
        json=dict(grams_per_part=30, hours_per_part=2, confirmed=True),
    )
    assert approve(client, p).status_code == 409


def test_requirements_change_invalidates_quote(client):
    key, _ = quoted(client)
    j = next(j for j in client.get("/api/state").json()["jobs"] if j["id"] == key)
    j["quantity"] = 4
    assert (
        client.patch(
            f"/api/jobs/{key}/requirements",
            json={
                k: j[k]
                for k in (
                    "title",
                    "request",
                    "quantity",
                    "material",
                    "units",
                    "deadline",
                )
            },
        ).status_code
        == 200
    )
    assert client.post(f"/api/jobs/{key}/proposals").status_code == 409


def test_naive_deadline_rejected(client):
    assert (
        client.post(
            "/api/jobs", json=dict(title="invalid", deadline="2029-01-01T12:00:00")
        ).status_code
        == 422
    )


def test_fractional_minutes_round_up_capacity(client):
    key = job(client)
    r = client.post(
        f"/api/jobs/{key}/quotes",
        json=dict(grams_per_part=1, hours_per_part=0.01, confirmed=True),
    )
    assert r.status_code == 201
    assert (
        r.json()["duration_minutes"] == 32
    )  # 1.8 minutes + 30 buffer, never rounded down


def test_expired_quote_blocks_approval(client):
    key, _ = quoted(client)
    p = plan(client, key)
    from backend import main

    with main.transaction() as c:
        q = main.get(c, p["quote_id"], "quote")
        q["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        main.put(c, "quote", q)
    assert approve(client, p).status_code == 409


def test_changed_duplicate_outage_payload_rejected(client):
    event = dict(
        printer_id="printer-a",
        starts_at=datetime.now(timezone.utc).isoformat(),
        ends_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        reason="test outage",
        event_key="duplicate-event-key",
    )
    assert client.post("/api/outages", json=event).status_code == 201
    event["reason"] = "different outage"
    assert client.post("/api/outages", json=event).status_code == 409
