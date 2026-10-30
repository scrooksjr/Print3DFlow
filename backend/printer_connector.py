"""Opt-in Bambu LAN telemetry. Subscribe-only; no publish or command API."""
import hashlib
import ipaddress
import json
import math
import os
import re
import ssl
import threading
import time
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from typing import Literal

_LOCK = threading.Lock()
STATES = {"IDLE", "RUNNING", "PAUSE", "FINISH", "FAILED", "PREPARE", "SLICING", "INIT"}


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


def config(printer_id):
    configured_id = os.getenv("BAMBU_READONLY_PRINTER_ID", "").strip()
    if not configured_id or configured_id != printer_id:
        return None
    host = os.getenv("BAMBU_READONLY_HOST", "").strip()
    serial = os.getenv("BAMBU_READONLY_SERIAL", "").strip()
    code = os.getenv("BAMBU_READONLY_ACCESS_CODE", "").strip()
    ca = os.getenv("BAMBU_READONLY_CA_FILE", "").strip()
    try:
        ip = ipaddress.ip_address(host)
        allowed = any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    except ValueError:
        allowed = False
    if not allowed or not re.fullmatch(r"[A-Za-z0-9_-]{5,64}", serial) or not code:
        raise ValueError("Complete the private IPv4 address, serial and access code in local configuration.")
    if ca and not Path(ca).is_file():
        raise ValueError("Configured TLS CA certificate file is unavailable.")
    return dict(host=host, serial=serial, code=code, ca=ca or None)


def settings_hash(settings):
    data = {**settings, "ca_digest": hashlib.sha256(Path(settings["ca"]).read_bytes()).hexdigest() if settings["ca"] else None}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def parse_report(payload):
    if len(payload) > 262144:
        raise ValueError("Oversized status report")
    value = json.loads(payload)
    report = value.get("print") if isinstance(value, dict) else None
    if not isinstance(report, dict) or report.get("gcode_state") not in STATES:
        raise ValueError("No supported execution state in report")
    result = dict(state=report["gcode_state"], error_known=False, error_present=None)
    error = report.get("print_error")
    if type(error) is int and error >= 0:
        result.update(error_known=True, error_present=error != 0)
    for source, name, maximum in (("mc_percent", "progress_percent", 100), ("nozzle_temper", "nozzle_c", 400), ("bed_temper", "bed_c", 150)):
        v = report.get(source)
        if type(v) in (int, float) and math.isfinite(v) and 0 <= v <= maximum:
            result[name] = v
    lights = report.get("lights_report", [])
    if isinstance(lights, list):
        for light in lights:
            if isinstance(light, dict) and light.get("node") == "chamber_light" and light.get("mode") in ("on", "off"):
                result["chamber_light"] = light["mode"]
    # Omit filenames, task IDs, serials, AMS payloads and unknown fields.
    return result


def tls_context(settings):
    # Network destination is an IP; the authenticated device identity is its serial.
    class SerialIdentityContext(ssl.SSLContext):
        def wrap_socket(self, sock, *args, **kwargs):
            kwargs["server_hostname"] = settings["serial"]
            return super().wrap_socket(sock, *args, **kwargs)

    context = SerialIdentityContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    if settings["ca"]:
        context.load_verify_locations(cafile=settings["ca"])
    return context


def probe(settings):
    import paho.mqtt.client as mqtt
    done = threading.Event()
    received = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="print3dflow-readonly-" + os.urandom(6).hex(), reconnect_on_failure=False)
    client.username_pw_set("bblp", settings["code"])
    # Hostname and CA validation stay enabled. No insecure-TLS fallback.
    client.tls_set_context(tls_context(settings))
    client.connect_timeout = 5
    topic = "device/" + settings["serial"] + "/report"

    def connected(c, userdata, flags, reason, properties):
        if reason.is_failure:
            received["failure"] = "authentication_failed"
            done.set()
        elif c.subscribe(topic, qos=0)[0] != mqtt.MQTT_ERR_SUCCESS:
            received["failure"] = "subscription_failed"
            done.set()

    def message(c, userdata, msg):
        if msg.topic != topic or msg.retain:
            return
        try:
            received["telemetry"] = parse_report(msg.payload)
            done.set()
        except (ValueError, TypeError, UnicodeError):
            return

    client.on_connect = connected
    client.on_message = message
    try:
        client.connect(settings["host"], 8883, keepalive=20)
        until = time.monotonic() + 12
        while not done.is_set() and time.monotonic() < until:
            if client.loop(timeout=0.5) != mqtt.MQTT_ERR_SUCCESS:
                return dict(status="connection_failed")
        if "telemetry" in received:
            return dict(status="verified_read_only", telemetry=received["telemetry"])
        return dict(status=received.get("failure", "no_fresh_status"))
    except ssl.SSLCertVerificationError:
        return dict(status="certificate_verification_failed")
    except (OSError, ssl.SSLError, ValueError):
        return dict(status="connection_failed")
    finally:
        client.disconnect()


def status(m, c, printer_id):
    try:
        settings = config(printer_id)
        configured = settings is not None
    except ValueError:
        return dict(connected=False, status="configuration_incomplete", source="bambu_lan_read_only")
    if not configured:
        return dict(connected=False, status="not_configured", source="no_live_telemetry")
    record = next((r for r in m.rows(c, "printer_connection") if r["printer_id"] == printer_id), None)
    fresh = bool(record and record.get("settings_hash") == settings_hash(settings) and record["status"] == "verified_read_only" and m.parse(record["expires_at"]) > m.now())
    result = dict(connected=fresh, status=record["status"] if record else "not_checked", source="bambu_lan_read_only", remote_start_allowed=False)
    if record:
        result.update(checked_at=record["checked_at"], expires_at=record["expires_at"], fresh=fresh)
        if fresh:
            result["telemetry"] = record.get("telemetry", {})
        elif record["status"] == "verified_read_only":
            result["status"] = "stale"
    return result


def register(app):
    from backend import main as m

    @app.get("/api/printers/{printer_id}/connection")
    def connection_status(printer_id: str):
        with m.engine.connect() as c:
            m.get(c, printer_id, "printer")
            return status(m, c, printer_id)

    @app.post("/api/printers/{printer_id}/connection/check")
    def check_connection(printer_id: str, body: Check):
        with m.engine.connect() as c:
            m.get(c, printer_id, "printer")
        try:
            settings = config(printer_id)
        except ValueError as exc:
            m.fail(str(exc), 422)
        if settings is None:
            m.fail("Configure this printer locally before checking its connection.", 409)
        if not _LOCK.acquire(blocking=False):
            m.fail("A printer connection check is already running.")
        try:
            result = probe(settings)
            with m.transaction() as c:
                record = dict(id="printer-connection-" + printer_id, printer_id=printer_id, checked_at=m.stamp(),
                              expires_at=(m.now() + timedelta(seconds=60)).isoformat(), settings_hash=settings_hash(settings), **result)
                m.put(c, "printer_connection", record)
                m.audit(c, None, "read_only_connection_checked", dict(printer_id=printer_id, status=result["status"], printer_commands_sent=False))
                return status(m, c, printer_id)
        finally:
            _LOCK.release()
