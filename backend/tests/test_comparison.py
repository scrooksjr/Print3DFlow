import copy
from datetime import timedelta

import pytest

from backend import comparison, integrations
from backend.tests.test_workflow import job


@pytest.fixture
def setup(client, monkeypatch):
    from backend import main as m

    defs = []
    for slug in ("a1", "a1mini", "x2d"):
        defs.append(
            dict(
                id=f"{slug}-pla-0.4-v1",
                printer={"id": f"bambu-{slug}"},
                bed_mm=[180, 180, 180],
            )
        )
    monkeypatch.setattr(integrations, "profile_definitions", lambda: defs)
    monkeypatch.setattr(
        integrations,
        "load_profile",
        lambda pid: (next(p for p in defs if p["id"] == pid), {}, pid + "-hash"),
    )

    def slice_mesh(mesh, units, pid, directory):
        hours = {"a1": 1, "a1mini": 2, "x2d": 3}[pid.split("-")[0]]
        return dict(
            profile_id=pid,
            profile_name=pid,
            profile_sha256=pid + "-hash",
            grams_per_part=hours * 20,
            hours_per_part=hours,
            seconds_per_part=hours * 3600,
            settings=dict(
                layer_height_mm=0.2, infill_percent=5, walls=2, supports=False
            ),
        )

    monkeypatch.setattr(integrations, "run_bambu_slice", slice_mesh)
    with m.transaction() as c:
        for d in defs:
            m.put(
                c,
                "printer",
                dict(
                    id=d["printer"]["id"],
                    name=d["printer"]["id"],
                    profile=d["id"],
                    active=True,
                    material="PLA",
                    bed_mm=d["bed_mm"],
                ),
            )
    return client, m, [p["id"] for p in defs]


def create(setup):
    c, m, ids = setup
    jid = job(c)
    r = c.post(
        f"/api/jobs/{jid}/comparisons", json={"confirmed": True, "profile_ids": ids}
    )
    assert r.status_code == 202, r.text
    b = c.get(f"/api/jobs/{jid}/comparisons").json()
    assert b["status"] == "ready", b
    return jid, b


def approve(c, b, o, **changes):
    body = dict(
        option_id=o["option_id"],
        total_cents=o["total_cents"],
        currency=o["currency"],
        confirmed=True,
        idempotency_key="comparison-approval-0001",
    )
    body.update(changes)
    return c.post("/api/comparisons/" + b["id"] + "/approve", json=body)


def advice(b):
    eligible = [
        o for o in b["options"] if o["on_time"] and not o["support_review_required"]
    ]
    return dict(
        model="test",
        source="meta_model_api",
        recommended_option_id=eligible[0]["option_id"] if eligible else None,
        assessments=[
            dict(option_id=o["option_id"], reason_codes=o["valid_reason_codes"])
            for o in b["options"]
        ],
    )


def test_independent_quotes_no_commit_until_exact_price_approval(setup, monkeypatch):
    c, m, _ = setup
    jid, b = create(setup)
    assert len(b["options"]) == 3
    state = c.get("/api/state").json()
    original = next(j for j in state["jobs"] if j["id"] == jid)
    assert not original.get("latest_quote_id") and not state["reservations"]
    assert len({o["total_cents"] for o in b["options"]}) == 3
    monkeypatch.setattr(comparison, "ask_meta", advice)
    r = c.post(
        "/api/comparisons/" + b["id"] + "/explanation",
        json={"consent_to_send_quote_totals": True},
    )
    assert r.status_code == 200, r.text
    assert c.get("/api/state").json()["reservations"] == []
    assert (
        next(j for j in c.get("/api/state").json()["jobs"] if j["id"] == jid)
        == original
    )
    o = b["options"][1]
    assert approve(c, b, o, total_cents=o["total_cents"] + 1).status_code == 409
    assert not c.get("/api/state").json()["reservations"]
    result = approve(c, b, o)
    assert result.status_code == 200, result.text
    assert result.json()["reservation"]["printer_id"] == o["printer_id"]
    assert result.json()["job"]["latest_quote_id"] == o["quote_id"]
    assert approve(c, b, o).json() == result.json()
    assert approve(c, b, b["options"][0]).status_code == 409


def test_recovery_reslices_reprices_and_replaces_only_after_approval(
    setup, monkeypatch
):
    c, m, ids = setup
    jid, b = create(setup)
    original_option = next(o for o in b["options"] if o["profile_id"].startswith("x2d"))
    initial = approve(c, b, original_option).json()
    old = initial["reservation"]
    assert (
        c.post(
            "/api/outages",
            json=dict(
                printer_id=old["printer_id"],
                starts_at=old["start"],
                ends_at=(m.parse(old["end"]) + timedelta(hours=2)).isoformat(),
                reason="Synthetic outage",
                event_key="comparison-outage-0001",
            ),
        ).status_code
        == 201
    )
    before = c.get("/api/state").json()
    r = c.post(
        f"/api/jobs/{jid}/comparisons", json={"confirmed": True, "profile_ids": ids}
    )
    assert r.status_code == 202, r.text
    b = c.get(f"/api/jobs/{jid}/comparisons").json()
    assert b["status"] == "ready", b
    monkeypatch.setattr(comparison, "ask_meta", advice)
    assert (
        c.post(
            "/api/comparisons/" + b["id"] + "/explanation",
            json={"consent_to_send_quote_totals": True},
        ).status_code
        == 200
    )
    after = c.get("/api/state").json()
    assert after["reservations"] == before["reservations"]
    assert after["jobs"] == before["jobs"]
    assert next(q for q in after["quotes"] if q["id"] == old["quote_id"]) == next(
        q for q in before["quotes"] if q["id"] == old["quote_id"]
    )
    alternative = next(o for o in b["options"] if o["profile_id"].startswith("a1-"))
    assert alternative["price_delta_cents"] < 0
    result = approve(c, b, alternative, idempotency_key="replacement-approval-0001")
    assert result.status_code == 200, result.text
    current = c.get("/api/state").json()
    assert not next(r for r in current["reservations"] if r["id"] == old["id"])[
        "active"
    ]
    assert sum(r["active"] for r in current["reservations"] if r["job_id"] == jid) == 1
    assert result.json()["reservation"]["printer_id"] == "bambu-a1"


@pytest.mark.parametrize("mutation", ["rates", "capacity", "profile"])
def test_changed_inputs_stale_and_block_approval(setup, monkeypatch, mutation):
    c, m, _ = setup
    jid, b = create(setup)
    if mutation == "profile":
        old = integrations.load_profile
        monkeypatch.setattr(
            integrations, "load_profile", lambda pid: (old(pid)[0], {}, "changed")
        )
    else:
        with m.transaction() as conn:
            if mutation == "rates":
                rate = copy.deepcopy(m.current_rates(conn))
                rate["rates"]["machine_per_hour"] = "99"
                m.put(conn, "rate_card", rate)
            else:
                p = m.get(conn, "bambu-a1", "printer")
                p["active"] = False
                m.put(conn, "printer", p)
    assert c.get(f"/api/jobs/{jid}/comparisons").json()["status"] == "stale"
    assert approve(c, b, b["options"][0]).status_code == 409
    assert not c.get("/api/state").json()["reservations"]


def test_meta_race_discards_explanation(setup, monkeypatch):
    c, m, _ = setup
    jid, b = create(setup)

    def changing(batch):
        with m.transaction() as conn:
            p = m.get(conn, "bambu-a1", "printer")
            p["active"] = False
            m.put(conn, "printer", p)
        return advice(batch)

    monkeypatch.setattr(comparison, "ask_meta", changing)
    assert (
        c.post(
            "/api/comparisons/" + b["id"] + "/explanation",
            json={"consent_to_send_quote_totals": True},
        ).status_code
        == 409
    )
    with m.engine.connect() as conn:
        assert not m.get(conn, b["id"], "comparison").get("advice")


@pytest.mark.parametrize("bad", ["reason", "option", "coverage"])
def test_meta_cannot_invent_comparison_facts(setup, bad):
    _, b = create(setup)
    response = advice(b)
    response.pop("model")
    response.pop("source")
    if bad == "reason":
        response["assessments"][0]["reason_codes"] = ["invented"]
    if bad == "option":
        response["recommended_option_id"] = "not-an-option"
    if bad == "coverage":
        response["assessments"].pop()
    with pytest.raises(ValueError):
        comparison.validate_advice(comparison.Advice.model_validate(response), b)


def test_provider_failure_does_not_block_manual_review_or_fake_advice(
    setup, monkeypatch
):
    c, m, _ = setup
    jid, b = create(setup)

    def failed(batch):
        raise integrations.IntegrationError("Unavailable")

    monkeypatch.setattr(comparison, "ask_meta", failed)
    assert (
        c.post(
            "/api/comparisons/" + b["id"] + "/explanation",
            json={"consent_to_send_quote_totals": True},
        ).status_code
        == 503
    )
    assert not c.get("/api/state").json()["reservations"]
    assert approve(c, b, b["options"][0]).status_code == 200


def test_unknown_support_share_blocks_approval(setup, monkeypatch):
    c, m, ids = setup
    original = integrations.run_bambu_slice

    def supported(*args):
        r = original(*args)
        r["settings"]["supports"] = True
        return r

    monkeypatch.setattr(integrations, "run_bambu_slice", supported)
    with m.transaction() as conn:
        rate = copy.deepcopy(m.current_rates(conn))
        rate["rates"]["support_surcharge_per_kg"] = "3"
        m.put(conn, "rate_card", rate)
    jid, b = create(setup)
    assert all(o["support_review_required"] for o in b["options"])
    assert advice(b)["recommended_option_id"] is None
    assert approve(c, b, b["options"][0]).status_code == 409
    r = c.post(
        f"/api/jobs/{jid}/comparisons",
        json=dict(
            confirmed=True,
            profile_ids=ids,
            support_percent_by_profile={pid: 0 for pid in ids},
        ),
    )
    assert r.status_code == 202
    b = c.get(f"/api/jobs/{jid}/comparisons").json()
    assert approve(c, b, b["options"][0]).status_code == 200


def test_late_options_have_no_recommendation_or_approval(setup):
    c, m, ids = setup
    jid = job(c, deadline_hours=1)
    assert (
        c.post(
            f"/api/jobs/{jid}/comparisons", json=dict(confirmed=True, profile_ids=ids)
        ).status_code
        == 202
    )
    b = c.get(f"/api/jobs/{jid}/comparisons").json()
    assert not any(o["on_time"] for o in b["options"])
    assert advice(b)["recommended_option_id"] is None
    assert approve(c, b, b["options"][0]).status_code == 409


def test_failed_slice_is_excluded_not_fabricated(setup, monkeypatch):
    c, m, _ = setup
    original = integrations.run_bambu_slice

    def partial(mesh, units, pid, directory):
        if pid.startswith("a1mini"):
            raise integrations.IntegrationError("Synthetic slice failure")
        return original(mesh, units, pid, directory)

    monkeypatch.setattr(integrations, "run_bambu_slice", partial)
    _, b = create(setup)
    assert len(b["options"]) == 2
    assert b["excluded"][0]["profile_id"] == "a1mini-pla-0.4-v1"
    assert not any(o["profile_id"].startswith("a1mini") for o in b["options"])


def test_unconfirmed_commit_cannot_change_price_or_capacity(setup):
    c, m, _ = setup
    _, b = create(setup)
    assert approve(c, b, b["options"][0], confirmed=False).status_code == 422
    assert not c.get("/api/state").json()["reservations"]


def test_comparison_requires_consent_before_external_price_disclosure(
    setup, monkeypatch
):
    c, m, _ = setup
    _, b = create(setup)

    def should_not_call(batch):
        raise AssertionError("Provider must not be called")

    monkeypatch.setattr(comparison, "ask_meta", should_not_call)
    for payload in ({}, {"consent_to_send_quote_totals": False}):
        assert (
            c.post(
                "/api/comparisons/" + b["id"] + "/explanation", json=payload
            ).status_code
            == 422
        )
