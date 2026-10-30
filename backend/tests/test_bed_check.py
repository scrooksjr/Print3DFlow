import copy
import io
import json
import threading
import time
from datetime import timedelta

import httpx
import pytest
from PIL import Image

from backend import main,bed_check as bed,printer_view,printer_connector as pc
from backend.tests.test_execution import ready,body
from backend.tests.test_printer_connector import configure


@pytest.fixture(autouse=True)
def clear_synthetic_camera_evidence():
    yield
    bed._CAPTURES.clear()
    for pid,session in list(printer_view._SESSIONS.items()):
        if session.get("id")=="synthetic-session":printer_view._SESSIONS.pop(pid,None)


def scene(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    stream=io.BytesIO();Image.new('RGB',(60,40),'gray').save(stream,format='JPEG')
    printer_view._SESSIONS[pid]=dict(id='synthetic-session',status='viewing',frame=stream.getvalue(),updated=time.monotonic(),deadline=time.monotonic()+120,stop=threading.Event(),settings_hash=pc.settings_hash(pc.config(pid)))
    return jid,pid


def capture(client,pid):
    r=client.post(f'/api/printers/{pid}/bed-check/capture',json={'session_id':'synthetic-session','confirmed':True})
    assert r.status_code==200,r.text
    return r.json()


def fake(monkeypatch,state='appears_empty'):
    reason={'appears_empty':'no_visible_object','occupied':'object_detected','uncertain':'poor_lighting'}[state]
    calls=[]
    def ask(image):
        calls.append(image)
        return bed.validate(bed.Assessment(state=state,bed_visible=state!='uncertain',image_usable=state!='uncertain',reason_codes=[reason])),'baseten','synthetic-meta-model'
    monkeypatch.setattr(bed,'ask_meta',ask)
    return calls


def test_consent_preview_and_no_commitments(client,monkeypatch):
    jid,pid=scene(client,monkeypatch);calls=fake(monkeypatch)
    before=copy.deepcopy(client.get('/api/state').json())
    c=capture(client,pid);assert not calls and 'image' not in c
    path=f'/api/printers/{pid}/bed-check'
    image=client.get(path+'/'+c['id']+'/image')
    assert image.status_code==200 and image.headers['cache-control'].startswith('no-store')
    assert client.post(path+'/assess',json={'capture_id':c['id'],'consent_to_send_image':False}).status_code==422
    assert not calls
    result=client.post(path+'/assess',json={'capture_id':c['id'],'consent_to_send_image':True})
    assert result.status_code==200,result.text
    x=result.json();assert len(calls)==1 and x['advisory_only'] and not x['operator_confirmation_current']
    assert any('visual bed' in b for b in client.get(f'/api/jobs/{jid}/execution').json()['blockers'])
    assert client.post(path+'/confirm',json={'assessment_id':x['id'],'physically_inspected_empty':False,'confirmed':True}).status_code==422
    review=client.post(path+'/confirm',json={'assessment_id':x['id'],'physically_inspected_empty':True,'confirmed':True})
    assert review.status_code==200 and review.json()['operator_confirmation_current']
    after=client.get('/api/state').json()
    for key in ('jobs','quotes','reservations','proposals'):assert before[key]==after[key]
    with main.engine.connect() as conn:
        stored=main.rows(conn,'bed_assessment')[0]
        assert 'image' not in stored and 'data:image' not in json.dumps(stored)


@pytest.mark.parametrize('state',['occupied','uncertain'])
def test_nonempty_or_uncertain_requires_separate_physical_review(client,monkeypatch,state):
    jid,pid=scene(client,monkeypatch);fake(monkeypatch,state)
    c=capture(client,pid);path=f'/api/printers/{pid}/bed-check'
    result=client.post(path+'/assess',json={'capture_id':c['id'],'consent_to_send_image':True}).json()
    assert result['state']==state and not result['operator_confirmation_current']
    readiness=client.get(f'/api/jobs/{jid}/execution').json()
    assert client.post(f'/api/jobs/{jid}/execution-review',json=body(readiness)).status_code==409


def test_expiry_replacement_and_configuration_changes(client,monkeypatch):
    jid,pid=scene(client,monkeypatch);fake(monkeypatch)
    first=capture(client,pid);second=capture(client,pid);path=f'/api/printers/{pid}/bed-check'
    assert client.post(path+'/assess',json={'capture_id':first['id'],'consent_to_send_image':True}).status_code==409
    future=main.now()+timedelta(seconds=61);monkeypatch.setattr(main,'now',lambda:future)
    assert client.get(path+'/'+second['id']+'/image').status_code==409
    assert client.post(path+'/assess',json={'capture_id':second['id'],'consent_to_send_image':True}).status_code==409


def test_stale_camera_or_different_session_cannot_capture(client,monkeypatch):
    jid,pid=scene(client,monkeypatch)
    printer_view._SESSIONS[pid]['updated']=time.monotonic()-3
    assert client.post(f'/api/printers/{pid}/bed-check/capture',json={'session_id':'synthetic-session','confirmed':True}).status_code==409


def test_provider_failure_and_expiry_during_inference(client,monkeypatch):
    jid,pid=scene(client,monkeypatch);c=capture(client,pid);path=f'/api/printers/{pid}/bed-check'
    def failed(image):raise ValueError('private provider details')
    monkeypatch.setattr(bed,'ask_meta',failed)
    response=client.post(path+'/assess',json={'capture_id':c['id'],'consent_to_send_image':True})
    assert response.status_code==503 and 'private provider' not in response.text
    def replaced(image):
        bed._CAPTURES.pop(pid,None)
        return bed.Assessment(state='appears_empty',bed_visible=True,image_usable=True,reason_codes=['no_visible_object']),'baseten','synthetic'
    monkeypatch.setattr(bed,'ask_meta',replaced)
    assert client.post(path+'/assess',json={'capture_id':c['id'],'consent_to_send_image':True}).status_code==409


def test_vision_payload_only_sends_image_and_static_prompt(monkeypatch):
    monkeypatch.setenv('META_PROVIDER','baseten');monkeypatch.setenv('BASETEN_API_KEY','synthetic-key')
    original=httpx.Client
    sent=[]
    def handle(request):
        payload=json.loads(request.content);sent.append(payload)
        result=dict(state='appears_empty',bed_visible=True,image_usable=True,reason_codes=['no_visible_object'])
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    result,provider,model=bed.ask_meta(b'synthetic-jpeg')
    assert result.state=='appears_empty' and provider=='baseten'
    assert sent[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    for word in ('synthetic-key','printer_id','customer','rate_card','serial'):
        assert word not in json.dumps(sent)


@pytest.mark.parametrize('state,visible,usable,reasons',[
    ('appears_empty',False,True,['no_visible_object']),
    ('appears_empty',True,True,['poor_lighting']),
    ('occupied',True,False,['object_detected']),
    ('uncertain',False,False,['no_visible_object']),
])
def test_contradictory_model_results_rejected(state,visible,usable,reasons):
    with pytest.raises(ValueError):bed.validate(bed.Assessment(state=state,bed_visible=visible,image_usable=usable,reason_codes=reasons))
