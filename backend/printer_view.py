"""Local camera viewing and narrowly scoped chamber-light controls. No print execution."""
import io
import hashlib
import json
import re
import threading
import time
import uuid
from urllib.parse import quote

from fastapi import Response
from pydantic import BaseModel, ConfigDict
from typing import Literal

from backend import printer_connector as pc

_SESSIONS = {}
_SESSION_LOCK = threading.Lock()


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class Light(Confirm):
    state: Literal["on", "off"]


def relay_packets(buffer, local_base):
    """Rewrite only RTSP control URLs; preserve interleaved RTP bytes exactly."""
    packets=[]
    while buffer:
        if buffer.startswith(b"$"):
            if len(buffer)<4:break
            size=4+int.from_bytes(buffer[2:4],"big")
            if len(buffer)<size:break
            packets.append(buffer[:size]);buffer=buffer[size:];continue
        boundary=buffer.find(b"\r\n\r\n")
        if boundary<0:break
        header=buffer[:boundary]
        match=re.search(br"(?im)^Content-Length:\s*(\d+)",header)
        length=int(match[1]) if match else 0
        if length>1048576:raise ValueError("Oversized camera control response")
        end=boundary+4+length
        if len(buffer)<end:break
        body=buffer[boundary+4:end]
        replace=lambda value:re.sub(br"rtsps?://[^/\s\r\n]+",local_base,value)
        header=replace(header);body=replace(body)
        if match:header=re.sub(br"(?im)^Content-Length:\s*\d+",b"Content-Length: "+str(len(body)).encode(),header)
        packets.append(header+b"\r\n\r\n"+body);buffer=buffer[end:]
    if len(buffer)>1048576:raise ValueError("Oversized camera relay buffer")
    return packets,buffer


def outbound_request(packet, settings):
    if packet.startswith(b"$"):return packet
    header,body=packet.split(b"\r\n\r\n",1)
    # The decoder sees loopback RTSP; the physical endpoint requires RTSPS URIs.
    remote=("rtsps://"+settings["host"]+":322").encode()
    header=re.sub(br"rtsp://127\.0\.0\.1:\d+",remote,header)
    auth=re.search(br"(?im)^Authorization: Digest (.+)$",header)
    if auth:
        fields={m[0].decode(): (m[1] or m[2]).decode() for m in re.findall(br'(\w+)=(?:"([^"]*)"|([^,\s]+))',auth[1])}
        algorithm=fields.get("algorithm","MD5").upper()
        if algorithm!="MD5" or fields.get("qop", "auth")!="auth":raise ValueError("Unsupported camera digest authentication")
        method=header.split(b" ",1)[0].decode()
        md5=lambda text:hashlib.md5(text.encode()).hexdigest()
        a1=md5("bblp:"+fields["realm"]+":"+settings["code"])
        a2=md5(method+":"+fields["uri"])
        parts=[a1,fields["nonce"]]
        if "qop" in fields:parts.extend([fields["nc"],fields["cnonce"],fields["qop"]])
        response=md5(":".join([*parts,a2]))
        replacement=re.sub(br'response="[^"]*"',b'response="'+response.encode()+b'"',auth[0])
        header=header[:auth.start()]+replacement+header[auth.end():]
    return header+b"\r\n\r\n"+body


def forward_camera_requests(local,remote,stop,port,settings):
    import socket
    try:
        pending=b""
        while not stop.is_set():
            # A quiet RTSP control channel is normal during an active video feed.
            try:data=local.recv(65536)
            except socket.timeout:continue
            if not data:break
            packets,pending=relay_packets(pending+data,("rtsp://127.0.0.1:"+str(port)).encode())
            for packet in packets:remote.sendall(outbound_request(packet,settings))
    except (OSError,ValueError,KeyError):pass
    finally:
        stop.set()
        try:remote.shutdown(socket.SHUT_RDWR)
        except OSError:pass


def camera_frames(settings):
    import av
    import socket
    av.logging.set_level(av.logging.PANIC)
    # Windows decoder TLS uses system trust rather than our CA bundle. Keep TLS
    # in Python, where chain and serial identity validation are enforced, then
    # relay the single stream through a short-lived loopback-only socket.
    with socket.create_connection((settings["host"],322),timeout=5) as raw:
        with pc.tls_context(settings).wrap_socket(raw,server_hostname=settings["serial"]) as remote:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1",0));listener.listen(1);listener.settimeout(5)
                port=listener.getsockname()[1]
                stop=threading.Event()
                def relay():
                    local=None
                    try:
                        local,_=listener.accept();local.settimeout(5)
                        def upstream():
                            forward_camera_requests(local,remote,stop,port,settings)
                        sender=threading.Thread(target=upstream,daemon=True);sender.start()
                        pending=b""
                        while not stop.is_set():
                            data=remote.recv(65536)
                            if not data:break
                            packets,pending=relay_packets(pending+data,("rtsp://127.0.0.1:"+str(port)).encode())
                            for packet in packets:local.sendall(packet)
                    except (OSError,ValueError):pass
                    finally:
                        stop.set()
                        if local:local.close()
                thread=threading.Thread(target=relay,daemon=True);thread.start()
                url="rtsp://bblp:"+quote(settings["code"],safe="")+"@127.0.0.1:"+str(port)+"/streaming/live/1"
                try:
                    with av.open(url,options=dict(rtsp_transport="tcp",protocol_whitelist="rtsp,tcp,rtp",allowed_media_types="video",http_proxy=""),timeout=(5,5)) as container:
                        last=0.0
                        for frame in container.decode(video=0):
                            current=time.monotonic()
                            if current-last<.5:continue
                            if frame.width>4096 or frame.height>2160:raise ValueError("Camera frame exceeds processing limit")
                            last=current
                            image=frame.to_image();image.thumbnail((1280,720))
                            data=io.BytesIO();image.save(data,format="JPEG",quality=75)
                            yield data.getvalue()
                finally:
                    stop.set()
                    try:remote.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    thread.join(timeout=1)


def camera_worker(session, settings):
    try:
        for frame in camera_frames(settings):
            if session["stop"].is_set() or time.monotonic() >= session["deadline"]:
                break
            with _SESSION_LOCK:
                session.update(frame=frame, updated=time.monotonic(), status="viewing")
            session["ready"].set()
    except Exception:
        with _SESSION_LOCK:
            session.update(status="camera_unavailable",frame=None)
        session["ready"].set()
    finally:
        with _SESSION_LOCK:
            session["frame"]=None
            if session["status"] != "camera_unavailable":session["status"]="stopped"
        session["ready"].set()


def light_switch(settings, requested):
    import paho.mqtt.client as mqtt
    result={"status":"unconfirmed","observed":None}
    sent=False
    topic="device/"+settings["serial"]+"/report"
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="print3dflow-light-"+uuid.uuid4().hex[:12],reconnect_on_failure=False)
    client.username_pw_set("bblp",settings["code"])
    client.tls_set_context(pc.tls_context(settings));client.connect_timeout=5
    payload={"system":dict(sequence_id=str(uuid.uuid4().int % 1000000000),command="ledctrl",led_node="chamber_light",led_mode=requested,led_on_time=500,led_off_time=500,loop_times=0,interval_time=0)}
    def connected(c,u,f,reason,properties):
        if reason.is_failure:result["status"]="authentication_failed"
        else:c.subscribe(topic,qos=0)
    def subscribed(c,u,mid,codes,properties):
        nonlocal sent
        if any(code.is_failure for code in codes):
            result["status"]="subscription_failed";return
        sent=c.publish("device/"+settings["serial"]+"/request",json.dumps(payload),qos=0,retain=False).rc==mqtt.MQTT_ERR_SUCCESS
    def message(c,u,msg):
        if not sent or msg.topic!=topic or msg.retain or len(msg.payload)>262144:return
        try:
            data=json.loads(msg.payload).get("print",{})
            for light in data.get("lights_report",[]):
                if light.get("node")=="chamber_light" and light.get("mode") in ("on","off"):
                    result["observed"]=light["mode"]
                    if result["observed"]==requested:result["status"]="confirmed"
        except (ValueError,TypeError,AttributeError):pass
    client.on_connect=connected;client.on_subscribe=subscribed;client.on_message=message
    try:
        client.connect(settings["host"],8883,keepalive=20)
        deadline=time.monotonic()+10
        while result["status"]=="unconfirmed" and time.monotonic()<deadline:
            if client.loop(timeout=.5)!=mqtt.MQTT_ERR_SUCCESS:break
    except Exception:result["status"]="connection_failed"
    finally:client.disconnect()
    return result


def register(app):
    from backend import main as m
    def configured(printer_id):
        with m.engine.connect() as c:m.get(c,printer_id,"printer")
        try:settings=pc.config(printer_id)
        except ValueError as exc:m.fail(str(exc),422)
        if settings is None:m.fail("Configure this printer's LAN connector first.")
        return settings
    def view(s):
        return dict(id=s["id"],status=s["status"],expires_in_seconds=max(0,int(s["deadline"]-time.monotonic())),recording=False)

    @app.post("/api/printers/{printer_id}/camera/start")
    def start_camera(printer_id:str,body:Confirm):
        settings=configured(printer_id)
        with _SESSION_LOCK:
            previous=_SESSIONS.get(printer_id)
            if previous and previous["thread"].is_alive():m.fail("A camera session is active or stopping; stop it before starting another.")
            s=dict(settings_hash=pc.settings_hash(settings),id=uuid.uuid4().hex,stop=threading.Event(),ready=threading.Event(),deadline=time.monotonic()+120,status="connecting",frame=None,updated=0)
            s["thread"]=threading.Thread(target=camera_worker,args=(s,settings),daemon=True)
            _SESSIONS[printer_id]=s
            s["thread"].start()
        s["ready"].wait(timeout=10)
        with m.transaction() as c:m.audit(c,None,"camera_view_requested",dict(printer_id=printer_id,recording=False,printer_commands_sent=False))
        return view(s)

    @app.get("/api/printers/{printer_id}/camera/{session_id}/status")
    def camera_status(printer_id:str,session_id:str):
        with _SESSION_LOCK:
            s=_SESSIONS.get(printer_id)
            if not s or s["id"]!=session_id:m.fail("Camera session not found.",404)
            return view(s)

    @app.get("/api/printers/{printer_id}/camera/{session_id}/frame")
    def camera_frame(printer_id:str,session_id:str):
        with _SESSION_LOCK:
            s=_SESSIONS.get(printer_id)
            if not s or s["id"]!=session_id:m.fail("Camera session not found.",404)
            if s["stop"].is_set() or time.monotonic()>=s["deadline"] or s["status"]!="viewing" or time.monotonic()-s["updated"]>5:
                s["frame"]=None;m.fail("Camera is stopped, unavailable or stale.")
            data=s["frame"]
        return Response(data,media_type="image/jpeg",headers={"Cache-Control":"no-store, max-age=0","Pragma":"no-cache"})

    @app.post("/api/printers/{printer_id}/camera/{session_id}/stop")
    def stop_camera(printer_id:str,session_id:str,body:Confirm):
        with _SESSION_LOCK:
            s=_SESSIONS.get(printer_id)
            if not s or s["id"]!=session_id:m.fail("Camera session not found.",404)
            s["stop"].set();s.update(status="stopped",frame=None)
        return view(s)

    @app.post("/api/printers/{printer_id}/chamber-light")
    def set_light(printer_id:str,body:Light):
        settings=configured(printer_id)
        with m.engine.connect() as c:
            status=pc.status(m,c,printer_id)
        if not status["connected"] or status.get("telemetry",{}).get("chamber_light") not in ("on","off"):
            m.fail("Refresh verified printer status with a reported chamber light before changing it.")
        if not pc._LOCK.acquire(blocking=False):m.fail("Another printer check or light action is running.")
        try:result=light_switch(settings,body.state)
        finally:pc._LOCK.release()
        with m.transaction() as c:
            m.audit(c,None,"chamber_light_requested",dict(printer_id=printer_id,requested=body.state,result=result["status"],print_commands_sent=False))
            for record in m.rows(c,"printer_connection"):
                if record["printer_id"]==printer_id:
                    record["expires_at"]=m.stamp();m.put(c,"printer_connection",record)
        return result
