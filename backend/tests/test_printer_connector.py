import copy
import json
from datetime import timedelta

import pytest
from backend import main, printer_connector as pc
from backend.tests.test_execution import ready, body


def configure(monkeypatch, printer_id):
    for k, v in dict(BAMBU_READONLY_PRINTER_ID=printer_id, BAMBU_READONLY_HOST="192.168.1.20", BAMBU_READONLY_SERIAL="SYNTHETIC-X2D", BAMBU_READONLY_ACCESS_CODE="synthetic-code", BAMBU_READONLY_CA_FILE="").items():
        monkeypatch.setenv(k, v)


@pytest.mark.parametrize('host', ['127.0.0.1','8.8.8.8','169.254.169.254','localhost','::1'])
def test_only_explicit_private_lan_addresses(monkeypatch, host):
    configure(monkeypatch, 'printer-a')
    monkeypatch.setenv('BAMBU_READONLY_HOST', host)
    with pytest.raises(ValueError): pc.config('printer-a')


def test_report_whitelist_and_unknown_error():
    t=pc.parse_report(json.dumps({'print':{'gcode_state':'RUNNING','mc_percent':25,'filename':'private.3mf','print_error':0}}).encode())
    assert t['state']=='RUNNING' and t['error_known'] and not t['error_present']
    assert 'private' not in json.dumps(t)
    assert not pc.parse_report(b'{"print":{"gcode_state":"IDLE"}}')['error_known']
    for payload in (b'{}',b'{"print":{"gcode_state":"unknown"}}',b'x'*262145):
        with pytest.raises(ValueError):pc.parse_report(payload)


def test_connection_check_consent_freshness_and_no_commitments(client, monkeypatch):
    jid, reservation=ready(client, monkeypatch)
    pid=reservation['printer_id'];configure(monkeypatch,pid)
    monkeypatch.setattr(pc,'probe',lambda settings:dict(status='verified_read_only',telemetry=dict(state='IDLE',error_known=True,error_present=False)))
    before=copy.deepcopy(client.get('/api/state').json())
    path=f'/api/printers/{pid}/connection'
    assert client.get(path).json()['status']=='not_checked'
    assert client.post(path+'/check',json={'confirmed':False}).status_code==422
    r=client.post(path+'/check',json={'confirmed':True})
    assert r.status_code==200 and r.json()['connected']
    for secret in ('synthetic-code','192.168.1.20','SYNTHETIC-X2D'):
        assert secret not in r.text
    after=client.get('/api/state').json()
    for k in ('jobs','quotes','reservations','proposals'):assert before[k]==after[k]
    assert client.get(f'/api/jobs/{jid}/execution').json()['connection']['connected']
    future=main.now()+timedelta(seconds=61)
    monkeypatch.setattr(main,'now',lambda:future)
    assert client.get(path).json()['status']=='stale'
    assert not client.get(path).json()['connected']


def test_changed_credentials_and_failed_check_invalidate_cached_success(client, monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    monkeypatch.setattr(pc,'probe',lambda settings:dict(status='verified_read_only',telemetry=dict(state='IDLE',error_known=True,error_present=False)))
    path=f'/api/printers/{pid}/connection'
    client.post(path+'/check',json={'confirmed':True})
    monkeypatch.setenv('BAMBU_READONLY_ACCESS_CODE','changed-code')
    assert not client.get(path).json()['connected']
    monkeypatch.setattr(pc,'probe',lambda settings:dict(status='certificate_verification_failed'))
    r=client.post(path+'/check',json={'confirmed':True}).json()
    assert not r['connected'] and 'telemetry' not in r


def test_busy_status_blocks_readiness_and_no_auto_start(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    monkeypatch.setattr(pc,'probe',lambda settings:dict(status='verified_read_only',telemetry=dict(state='RUNNING',error_known=True,error_present=False)))
    client.post(f'/api/printers/{pid}/connection/check',json={'confirmed':True})
    s=client.get(f'/api/jobs/{jid}/execution').json()
    assert any('idle' in b for b in s['blockers']) and not s['remote_start_allowed']
    assert client.post(f'/api/jobs/{jid}/execution-review',json=body(s)).status_code==409


def test_configured_assisted_connection_must_be_fresh(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    client.post(f'/api/printers/{pid}/execution-policy',json={'mode':'assisted','confirmed':True})
    s=client.get(f'/api/jobs/{jid}/execution').json()
    assert any('telemetry' in b for b in s['blockers'])


def test_probe_subscribes_only_and_rejects_retained_packets(monkeypatch):
    import ssl
    from types import SimpleNamespace
    import paho.mqtt.client as mqtt
    seen=[]
    class Fake:
        def __init__(self,*args,**kwargs):self.step=0
        def username_pw_set(self,*args):pass
        def tls_set_context(self,context):
            assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        def connect(self,host,port,keepalive):
            assert port==8883
            self.on_connect(self,None,None,SimpleNamespace(is_failure=False),None)
        def subscribe(self,topic,qos):seen.append(topic);return (0,1)
        def loop(self,timeout):
            self.step+=1
            self.on_message(self,None,SimpleNamespace(topic='device/SYNTHETIC-X2D/report',retain=self.step==1,payload=b'{"print":{"gcode_state":"IDLE","print_error":0}}'))
            return 0
        def disconnect(self):seen.append('disconnect')
        def publish(self,*args,**kwargs):raise AssertionError('Printer commands forbidden')
    monkeypatch.setattr(mqtt,'Client',Fake)
    r=pc.probe(dict(host='192.168.1.20',serial='SYNTHETIC-X2D',code='synthetic-code',ca=None))
    assert r['status']=='verified_read_only'
    assert seen==['device/SYNTHETIC-X2D/report','disconnect']


def test_tls_verifies_saved_serial_identity_not_ip(monkeypatch):
    import ssl
    captured={}
    def wrap(self, sock, *args, **kwargs):
        captured.update(kwargs)
        return 'verified-socket'
    monkeypatch.setattr(ssl.SSLContext,'wrap_socket',wrap)
    ctx=pc.tls_context(dict(serial='SYNTHETIC-X2D',ca=None))
    assert ctx.check_hostname and ctx.verify_mode==ssl.CERT_REQUIRED
    assert ctx.wrap_socket(object(),server_hostname='192.168.1.20')=='verified-socket'
    assert captured['server_hostname']=='SYNTHETIC-X2D'
