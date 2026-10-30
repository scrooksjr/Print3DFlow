import copy
import hashlib
import json
import time
from types import SimpleNamespace

from backend import main, printer_connector as pc, printer_view as view
from backend.tests.test_printer_connector import configure
from backend.tests.test_execution import ready


def seed_connection(monkeypatch,pid):
    configure(monkeypatch,pid)
    with main.transaction() as c:
        main.put(c,'printer_connection',dict(id='printer-connection-'+pid,printer_id=pid,status='verified_read_only',settings_hash=pc.settings_hash(pc.config(pid)),checked_at=main.stamp(),expires_at=(main.now()+__import__('datetime').timedelta(seconds=60)).isoformat(),telemetry=dict(state='IDLE',error_known=True,error_present=False,chamber_light='on')))


def test_light_requires_confirmation_and_cannot_accept_arbitrary_commands(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];seed_connection(monkeypatch,pid)
    calls=[]
    monkeypatch.setattr(view,'light_switch',lambda settings,state:calls.append(state) or dict(status='confirmed',observed=state))
    path=f'/api/printers/{pid}/chamber-light'
    assert client.post(path,json={'state':'off','confirmed':False}).status_code==422
    assert client.post(path,json={'state':'off','confirmed':True,'command':'project_file'}).status_code==422
    assert client.post(path,json={'state':'start','confirmed':True}).status_code==422
    assert not calls
    before=copy.deepcopy(client.get('/api/state').json())
    result=client.post(path,json={'state':'off','confirmed':True})
    assert result.status_code==200 and result.json()['status']=='confirmed'
    assert calls==['off']
    after=client.get('/api/state').json()
    for key in ('jobs','quotes','reservations','proposals'):assert before[key]==after[key]
    assert not client.get(f'/api/printers/{pid}/connection').json()['connected']


def test_light_stale_status_blocks_publish(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    monkeypatch.setattr(view,'light_switch',lambda *args: (_ for _ in ()).throw(AssertionError('Must not publish')))
    assert client.post(f'/api/printers/{pid}/chamber-light',json={'state':'on','confirmed':True}).status_code==409


def test_light_transport_sends_only_whitelisted_light_command(monkeypatch):
    import paho.mqtt.client as mqtt
    sent=[]
    class Fake:
        def __init__(self,*args,**kwargs):pass
        def username_pw_set(self,*args):pass
        def tls_set_context(self,context):assert context.check_hostname
        def connect(self,*args,**kwargs):self.on_connect(self,None,None,SimpleNamespace(is_failure=False),None)
        def subscribe(self,topic,qos):self.on_subscribe(self,None,1,[SimpleNamespace(is_failure=False)],None)
        def publish(self,topic,payload,qos,retain):sent.append((topic,json.loads(payload),retain));return SimpleNamespace(rc=0)
        def loop(self,timeout):
            self.on_message(self,None,SimpleNamespace(topic='device/SYNTHETIC-X2D/report',retain=False,payload=b'{"print":{"lights_report":[{"node":"chamber_light","mode":"off"}]}}'))
            return 0
        def disconnect(self):pass
    monkeypatch.setattr(mqtt,'Client',Fake)
    result=view.light_switch(dict(host='192.168.1.20',serial='SYNTHETIC-X2D',code='synthetic-code',ca=None),'off')
    assert result['status']=='confirmed' and len(sent)==1
    assert list(sent[0][1])==['system']
    assert sent[0][1]['system']['command']=='ledctrl' and sent[0][1]['system']['led_mode']=='off'
    assert not sent[0][2]


def test_camera_start_stop_and_expired_frames(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    def frames(settings):
        for _ in range(100):
            yield b'\xff\xd8synthetic-frame'
            time.sleep(.01)
    monkeypatch.setattr(view,'camera_frames',frames)
    path=f'/api/printers/{pid}/camera'
    assert client.post(path+'/start',json={'confirmed':False}).status_code==422
    result=client.post(path+'/start',json={'confirmed':True})
    assert result.status_code==200 and not result.json()['recording']
    sid=result.json()['id'];framepath=path+'/'+sid+'/frame'
    image=client.get(framepath)
    assert image.status_code==200 and image.headers['cache-control'].startswith('no-store')
    assert client.post(path+'/start',json={'confirmed':True}).status_code==409
    client.post(path+'/'+sid+'/stop',json={'confirmed':True})
    assert client.get(framepath).status_code==409
    assert view._SESSIONS[pid]['frame'] is None
    view._SESSIONS[pid]['thread'].join(timeout=1)
    assert not view._SESSIONS[pid]['thread'].is_alive()


def test_camera_failure_sanitized(client,monkeypatch):
    jid,r=ready(client,monkeypatch);pid=r['printer_id'];configure(monkeypatch,pid)
    def failed(settings):raise ValueError('synthetic-code must not leak')
    monkeypatch.setattr(view,'camera_frames',failed)
    result=client.post(f'/api/printers/{pid}/camera/start',json={'confirmed':True})
    assert result.json()['status']=='camera_unavailable'
    assert 'synthetic-code' not in result.text
    assert view._SESSIONS[pid]['frame'] is None


def test_relay_preserves_video_and_rewrites_control_lengths():
    body=b'a=control:rtsps://192.168.1.20:322/streaming/live/1\r\n'
    message=b'RTSP/1.0 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
    rtp=b'$\x00\x00\x04test'
    packets,pending=view.relay_packets(message+rtp,b'rtsp://127.0.0.1:12345')
    assert not pending and packets[1]==rtp
    header,newbody=packets[0].split(b'\r\n\r\n')
    assert ('Content-Length: '+str(len(newbody))).encode() in header
    assert b'192.168' not in packets[0]
    packets,pending=view.relay_packets(message[:10],b'rtsp://127.0.0.1:12345')
    assert not packets and pending==message[:10]


def test_digest_recomputed_for_secure_remote_uri():
    packet=b'DESCRIBE rtsp://127.0.0.1:12345/streaming/live/1 RTSP/1.0\r\nAuthorization: Digest username="bblp", realm="realm", nonce="nonce", uri="rtsp://127.0.0.1:12345/streaming/live/1", response="old"\r\n\r\n'
    result=view.outbound_request(packet,dict(host='192.168.1.20',code='synthetic-code'))
    assert b'rtsps://192.168.1.20:322/streaming/live/1' in result and b'response="old"' not in result
    assert b'synthetic-code' not in result
    md5=lambda text:hashlib.md5(text.encode()).hexdigest()
    expected=md5(md5('bblp:realm:synthetic-code')+':nonce:'+md5('DESCRIBE:rtsps://192.168.1.20:322/streaming/live/1'))
    assert expected.encode() in result


def test_idle_control_timeout_does_not_close_active_video():
    import socket
    import threading
    request=b'OPTIONS rtsp://127.0.0.1:12345/streaming/live/1 RTSP/1.0\r\nCSeq: 1\r\n\r\n'
    class Local:
        def __init__(self):self.messages=iter([socket.timeout(),socket.timeout(),request,b''])
        def recv(self,n):
            result=next(self.messages)
            if isinstance(result,Exception):raise result
            return result
    class Remote:
        def __init__(self):self.sent=[];self.closed=False
        def sendall(self,data):self.sent.append(data)
        def shutdown(self,how):self.closed=True
    remote=Remote();stop=threading.Event()
    view.forward_camera_requests(Local(),remote,stop,12345,dict(host='192.168.1.20',code='synthetic-code'))
    assert len(remote.sent)==1
    assert remote.sent[0].startswith(b'OPTIONS rtsps://192.168.1.20:322/')
    assert remote.closed and stop.is_set()
