import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.tests.test_workflow import quoted, plan, approve


def scenario(client):
    key, q = quoted(client)
    first = approve(client, plan(client, key)).json()["reservation"]
    event = client.post(
        "/api/outages",
        json=dict(
            printer_id=first["printer_id"],
            starts_at=first["start"],
            ends_at=(
                datetime.fromisoformat(first["end"]) + timedelta(hours=6)
            ).isoformat(),
            reason="private reason that must not go to Meta",
            event_key="recovery-explain-outage",
        ),
    )
    assert event.status_code == 201
    p = client.post("/api/jobs/" + key + "/recovery")
    assert p.status_code == 201, p.text
    return key, q, first, p.json()


def mock_provider(
    monkeypatch, mutate=None, invalid=None, recommend_last=False, status=200
):
    monkeypatch.setenv("META_API_KEY", "isolated-recovery-test-key")
    original = httpx.Client
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        facts = json.loads(payload["messages"][1]["content"])
        requests.append(facts)
        options = facts["options"]
        eligible = [o["option_id"] for o in options if o["on_time"]]
        recommendation = (
            (eligible[-1] if recommend_last else eligible[0]) if eligible else None
        )
        result = dict(
            recommended_option_id=recommendation,
            assessments=[
                dict(option_id=o["option_id"], reason_codes=o["valid_reason_codes"])
                for o in options
            ],
        )
        if invalid:
            result = invalid(result)
        if mutate:
            mutate()
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(result)},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return requests


def test_explanation_is_grounded_cached_and_cannot_change_reservations(
    client, monkeypatch
):
    key, q, old, p = scenario(client)
    before = client.get("/api/state").json()["reservations"]
    calls = mock_provider(monkeypatch)
    r = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["source"] == "meta_model_api" and result["approval_required"]
    assert len(result["options"]) == 2
    assert any(
        "earliest verified completion" in text
        for o in result["options"]
        for text in o["reasons"]
    )
    assert client.get("/api/state").json()["reservations"] == before
    assert client.post("/api/proposals/" + p["id"] + "/explanation").json() == result
    assert len(calls) == 1
    sent = json.dumps(calls[0])
    assert all(
        value not in sent
        for value in [
            "private reason",
            "Fixture bracket",
            "Atlas A",
            "Atlas B",
            "total_cents",
            "rate_card",
            "PLA material",
        ]
    )
    assert (
        client.get("/api/proposals/" + p["id"] + "/explanation").json()["status"]
        == "ready"
    )


def test_recommendation_does_not_select_or_approve_and_operator_can_choose(
    client, monkeypatch
):
    key, q, old, p = scenario(client)
    mock_provider(monkeypatch, recommend_last=True)
    r = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert r.status_code == 200
    recommendation = r.json()["recommended_option_id"]
    assert recommendation != p["choice"]["option_id"]
    current = next(
        x for x in client.get("/api/state").json()["proposals"] if x["id"] == p["id"]
    )
    assert current["choice"] == p["choice"] and current["status"] == "proposed"
    chosen = client.post(
        "/api/proposals/" + p["id"] + "/select-option",
        json={"option_id": recommendation},
    )
    assert (
        chosen.status_code == 200
        and chosen.json()["choice"]["option_id"] == recommendation
    )
    assert next(
        x
        for x in client.get("/api/state").json()["reservations"]
        if x["id"] == old["id"]
    )["active"]
    assert (
        client.get("/api/proposals/" + p["id"] + "/explanation").json()["status"]
        == "ready"
    )
    approved = approve(client, chosen.json(), "explicit-recovery-approval")
    assert approved.status_code == 200, approved.text
    state = client.get("/api/state").json()
    assert sum(r["active"] for r in state["reservations"] if r["job_id"] == key) == 1
    assert next(x for x in state["quotes"] if x["id"] == q["id"]) == q


@pytest.mark.parametrize(
    "invalid",
    [
        lambda r: {**r, "recommended_option_id": "invented-printer"},
        lambda r: {**r, "assessments": r["assessments"][:1]},
        lambda r: {**r, "assessments": [r["assessments"][0], r["assessments"][0]]},
        lambda r: {**r, "change_reservation": True},
        lambda r: {
            **r,
            "assessments": [
                dict(option_id=a["option_id"], reason_codes=["misses_deadline"])
                for a in r["assessments"]
            ],
        },
    ],
)
def test_unsupported_claims_are_rejected_without_mutation(client, monkeypatch, invalid):
    key, q, old, p = scenario(client)
    before = client.get("/api/state").json()["reservations"]
    mock_provider(monkeypatch, invalid=invalid)
    r = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert r.status_code == 503 and "isolated-recovery-test-key" not in r.text
    assert client.get("/api/state").json()["reservations"] == before
    current = next(
        x for x in client.get("/api/state").json()["proposals"] if x["id"] == p["id"]
    )
    assert not current.get("explanation_id")


def capacity_change():
    from backend import main

    with main.transaction() as c:
        start = main.now() + timedelta(days=10)
        main.put(
            c,
            "outage",
            dict(
                id=main.uid(),
                printer_id="printer-a",
                starts_at=start.isoformat(),
                ends_at=(start + timedelta(hours=1)).isoformat(),
                reason="test capacity change",
                event_key=main.uid(),
                source="operator_simulated",
                affected_jobs=[],
            ),
        )


def test_capacity_changed_during_model_call_discards_result(client, monkeypatch):
    key, q, old, p = scenario(client)
    mock_provider(monkeypatch, mutate=capacity_change)
    response = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert response.status_code == 409
    current = next(
        x for x in client.get("/api/state").json()["proposals"] if x["id"] == p["id"]
    )
    assert not current.get("explanation_id")


def test_stale_explanation_hidden_and_blocks_approval(client, monkeypatch):
    key, q, old, p = scenario(client)
    mock_provider(monkeypatch)
    assert client.post("/api/proposals/" + p["id"] + "/explanation").status_code == 200
    capacity_change()
    stale = client.get("/api/proposals/" + p["id"] + "/explanation").json()
    assert stale["status"] == "stale" and "options" not in stale
    assert approve(client, p, "stale-rationale-approval").status_code == 409
    assert next(
        r
        for r in client.get("/api/state").json()["reservations"]
        if r["id"] == old["id"]
    )["active"]
    # If the options remain feasible, an explicit fresh explanation can revalidate them.
    assert client.post("/api/proposals/" + p["id"] + "/explanation").status_code == 200
    assert approve(client, p, "fresh-rationale-approval").status_code == 200


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_failure_keeps_manual_approval_available(client, monkeypatch, status):
    key, q, old, p = scenario(client)
    mock_provider(monkeypatch, status=status)
    assert client.post("/api/proposals/" + p["id"] + "/explanation").status_code == 503
    assert approve(client, p, "manual-recovery-approval").status_code == 200


def test_no_on_time_option_is_not_recommended(client, monkeypatch):
    key, q, old, p = scenario(client)
    end = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    for index, printer in enumerate(["printer-a", "printer-b"]):
        assert (
            client.post(
                "/api/outages",
                json=dict(
                    printer_id=printer,
                    starts_at=old["start"],
                    ends_at=end,
                    reason="test long outage",
                    event_key="long-outage-" + str(index),
                ),
            ).status_code
            == 201
        )
    p = client.post("/api/jobs/" + key + "/recovery").json()
    mock_provider(monkeypatch)
    r = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert r.status_code == 200, r.text
    assert r.json()["recommended_option_id"] is None
    assert all(not o["on_time"] for o in r.json()["options"])
    assert approve(client, p, "late-plan-rejected").status_code == 409


def test_single_compatible_option_is_explicit(client, monkeypatch):
    key, q, old, p = scenario(client)
    from backend import main

    with main.transaction() as c:
        printer = main.get(c, "printer-b", "printer")
        printer["active"] = False
        main.put(c, "printer", printer)
    p = client.post("/api/jobs/" + key + "/recovery").json()
    mock_provider(monkeypatch)
    r = client.post("/api/proposals/" + p["id"] + "/explanation")
    assert r.status_code == 200, r.text
    assert len(r.json()["options"]) == 1
    assert "no_compatible_alternative" in r.json()["options"][0]["reason_codes"]


def test_option_selection_is_limited_to_verified_options(client):
    key, q, old, p = scenario(client)
    assert (
        client.post(
            "/api/proposals/" + p["id"] + "/select-option",
            json={"option_id": "invented"},
        ).status_code
        == 422
    )
