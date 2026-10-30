import copy
from datetime import timedelta

from backend import main
from backend.tests.test_workflow import quoted, plan, approve, job


def scheduled(client):
    jid, quote = quoted(client)
    result = approve(client, plan(client, jid))
    assert result.status_code == 200
    return jid, result.json()["reservation"]


def ready(client, monkeypatch):
    jid, reservation = scheduled(client)
    # Synthetic native evidence for isolated readiness tests; no physical printer.
    with main.transaction() as c:
        q = main.get(c, reservation["quote_id"], "quote")
        q["source"] = "bambu_studio"
        main.put(c, "quote", q)
    monkeypatch.setattr(main, "valid_quote", lambda c, j: main.get(c, j["latest_quote_id"], "quote"))
    return jid, reservation


def body(state):
    return dict(snapshot=state["snapshot"], artifact_reviewed=True, filament_loaded=True,
                sufficient_material=True, plate_clear=True, printer_ready=True, confirmed=True)


def test_execution_blocks_without_reservation_and_native_slice(client):
    jid = job(client)
    s = client.get(f"/api/jobs/{jid}/execution").json()
    assert s["blockers"] and not s["remote_start_allowed"]
    assert client.post(f"/api/jobs/{jid}/execution-review", json=body(s)).status_code == 409
    jid, _ = scheduled(client)
    s = client.get(f"/api/jobs/{jid}/execution").json()
    assert any("native slicer" in b for b in s["blockers"])


def test_manual_default_automatic_rejected(client):
    jid, r = scheduled(client)
    path = f"/api/printers/{r['printer_id']}/execution-policy"
    assert client.get(f"/api/jobs/{jid}/execution").json()["policy"]["mode"] == "manual"
    assert client.post(path, json=dict(mode="automatic", confirmed=True)).status_code == 409
    assert client.post(path, json=dict(mode="assisted", confirmed=False)).status_code == 422
    assert client.post(path, json=dict(mode="assisted", confirmed=True)).status_code == 200
    s = client.get(f"/api/jobs/{jid}/execution").json()
    assert s["policy"]["mode"] == "assisted" and not s["automatic_execution_allowed"]
    assert s["connection"]["connected"] is False


def test_review_requires_all_checks_no_commitments_or_commands(client, monkeypatch):
    jid, _ = ready(client, monkeypatch)
    path = f"/api/jobs/{jid}/execution"
    s = client.get(path).json()
    before = copy.deepcopy(client.get('/api/state').json())
    b = body(s)
    b['plate_clear'] = False
    assert client.post(path+'-review', json=b).status_code == 422
    result = client.post(path+'-review', json=body(s))
    assert result.status_code == 200, result.text
    assert result.json()['review_current'] and not result.json()['remote_start_allowed']
    assert result.json()['last_review']['source'] == 'operator_attestation_not_telemetry'
    after = client.get('/api/state').json()
    for key in ('jobs','quotes','reservations','proposals'):
        assert after[key] == before[key]
    assert after['audit'][-1]['details']['printer_commands_sent'] is False


def test_policy_change_invalidates_review_and_stale_submission(client, monkeypatch):
    jid, r = ready(client, monkeypatch)
    path = f"/api/jobs/{jid}/execution"
    s = client.get(path).json()
    assert client.post(path+'-review', json=body(s)).status_code == 200
    client.post(f"/api/printers/{r['printer_id']}/execution-policy", json=dict(mode='assisted', confirmed=True))
    assert not client.get(path).json()['review_current']
    assert client.post(path+'-review', json=body(s)).status_code == 409


def test_expiry_and_outage_fail_closed(client, monkeypatch):
    jid, r = ready(client, monkeypatch)
    path = f"/api/jobs/{jid}/execution"
    s = client.get(path).json()
    client.post(path+'-review', json=body(s))
    future = main.now() + timedelta(minutes=11)
    monkeypatch.setattr(main, 'now', lambda: future)
    assert not client.get(path).json()['review_current']
    with main.transaction() as c:
        main.put(c, 'outage', dict(id='execution-outage', printer_id=r['printer_id'], starts_at=r['start'], ends_at=r['end']))
    s = client.get(path).json()
    assert any('outage' in b for b in s['blockers'])
    assert client.post(path+'-review', json=body(s)).status_code == 409


def test_invalid_quote_evidence_blocks_review(client, monkeypatch):
    from fastapi import HTTPException
    jid, _ = ready(client, monkeypatch)
    def invalid(c, j):
        raise HTTPException(409, 'changed')
    monkeypatch.setattr(main, 'valid_quote', invalid)
    s = client.get(f'/api/jobs/{jid}/execution').json()
    assert any('evidence' in b for b in s['blockers'])
