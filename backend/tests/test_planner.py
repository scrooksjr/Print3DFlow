import copy
import json

import httpx
import pytest

from backend import planner, integrations
from backend.tests.test_workflow import job
from backend.tests.test_comparison import setup, create


def meta(monkeypatch, bad_tool=None, bad_decision=None, mutate=None):
    monkeypatch.setenv("META_API_KEY", "test-planner-key")
    original = httpx.Client
    sent = []

    def handle(request):
        body = json.loads(request.content)
        sent.append(body)
        results = {}
        for m in body['messages']:
            if m['role'] == 'tool':
                results[m['tool_call_id']] = json.loads(m['content'])
        if not results:
            calls = [dict(id='readiness',type='function',function=dict(name=bad_tool or 'check_job_readiness',arguments='{}')),
                     dict(id='comparison',type='function',function=dict(name='read_verified_comparison',arguments='{}'))]
        else:
            ready, options = results['readiness'], results['comparison']
            eligible = [o for o in options['options'] if o['on_time'] and not o['support_review_required']]
            action = 'resolve_requirements' if ready['status']=='blocked' else 'request_comparison' if options['status']!='verified' else 'review_approval' if eligible else 'no_approvable_option'
            args = dict(next_action=action,recommended_option_id=eligible[0]['option_id'] if eligible else None,
                        evidence_ids=eligible[0]['evidence_ids'][:1] if eligible else ready['evidence_ids'][:1] if ready['status']=='blocked' else options['evidence_ids'][:1])
            if bad_decision:
                args.update(bad_decision)
            if mutate:
                mutate()
            calls = [dict(id='submit',type='function',function=dict(name='submit_plan',arguments=json.dumps(args)))]
        return httpx.Response(200,json={'choices':[dict(finish_reason='tool_calls',message=dict(role='assistant',tool_calls=calls))]})

    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return sent


def test_planner_requires_consent_and_does_not_send_customer_or_finances(client, monkeypatch):
    jid = job(client)
    before = copy.deepcopy(client.get('/api/state').json())
    sent = meta(monkeypatch)
    assert client.post('/api/jobs/'+jid+'/planner',json={}).status_code == 422
    r = client.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True})
    assert r.status_code == 201, r.text
    p = r.json()
    assert len(p['trail']) == 2 and p['source']=='meta_model_api_tool_calls'
    assert p['recommendation']['next_action']=='request_comparison'
    assert not p['stale']
    payload = json.dumps(sent)
    for excluded in ('Three PLA parts', 'Fixture bracket', 'total_cents', 'rates', 'filename', 'printer_name'):
        assert excluded not in payload
    after = client.get('/api/state').json()
    for k in ('jobs','quotes','reservations','proposals'):
        assert after[k]==before[k]


@pytest.mark.parametrize('bad', ['approve_reservation','create_quote','run_shell'])
def test_unlisted_tools_cannot_execute(client, monkeypatch, bad):
    jid = job(client)
    meta(monkeypatch,bad_tool=bad)
    assert client.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True}).status_code==503
    assert client.get('/api/jobs/'+jid+'/planner').json()['status']=='not_requested'
    assert not client.get('/api/state').json()['reservations']


def test_verified_comparison_and_stale_inputs_preserve_commitments(setup, monkeypatch):
    c,m,_ = setup
    jid,batch = create(setup)
    before = c.get('/api/state').json()
    meta(monkeypatch)
    r = c.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True})
    assert r.status_code==201,r.text
    assert r.json()['recommendation']['next_action']=='review_approval'
    assert not r.json()['stale']
    after = c.get('/api/state').json()
    assert before['jobs']==after['jobs'] and before['quotes']==after['quotes'] and before['reservations']==after['reservations']
    with m.transaction() as conn:
        j=m.get(conn,jid,'job');j['version']+=1;m.put(conn,'job',j)
    p = c.get('/api/jobs/'+jid+'/planner').json()
    assert p['stale'] and p['recommendation'] is None


def test_invalid_recommendation_and_invented_evidence_rejected(client, monkeypatch):
    jid=job(client)
    meta(monkeypatch,bad_decision={'recommended_option_id':'made-up-option','evidence_ids':['fake-fact']})
    assert client.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True}).status_code==503


def test_custom_finish_blocker_is_grounded(client, monkeypatch):
    from backend import main as m
    jid=job(client)
    with m.transaction() as conn:
        j=m.get(conn,jid,'job');j['finish']='painting';m.put(conn,'job',j)
    meta(monkeypatch)
    r=client.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True})
    assert r.status_code==201,r.text
    assert r.json()['recommendation']['next_action']=='resolve_requirements'
    assert 'finish_review' in r.json()['recommendation']['evidence_ids']
    assert not client.get('/api/state').json()['quotes']


def test_changes_during_inference_discard_plan(client, monkeypatch):
    from backend import main as m
    jid=job(client)
    def change():
        with m.transaction() as conn:
            j=m.get(conn,jid,'job');j['version']+=1;m.put(conn,'job',j)
    meta(monkeypatch,mutate=change)
    assert client.post('/api/jobs/'+jid+'/planner',json={'consent_to_send_planning_facts':True}).status_code==409
