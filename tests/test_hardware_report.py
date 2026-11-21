import io
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from app.hardware_tests.client import AgentClient, AgentError
from app.hardware_tests.esp_usb import EspUsbClient
from app.hardware_tests.measurement import LOW_FPS, analyze, simulate
from app.reports.export import export, report_data
from app.utils.settings import DEFAULTS
from orange_pi.agent import server

def test_low_fps_no_exact_gtg():
    options = dict(DEFAULTS, camera_fps=30)
    samples = simulate(options)
    result = analyze(samples, options["hold"], True)
    assert result["fps"] == 30
    assert len(result["transitions"]) == 8
    assert all(row["optical_10_90_ms"] is None for row in result["transitions"])
    assert result["gtg_ms"] is None
    assert LOW_FPS in result["warnings"]
    assert result["quality"] == "Синтетические данные"

def test_resolved_optical_bounds():
    options = dict(DEFAULTS, camera_fps=240)
    result = analyze(simulate(options), options["hold"], True, timing="Simulation")
    assert result["summaries"]["↑"]["median_optical_ms"] > 15
    assert result["summaries"]["↓"]["median_optical_ms"] < 60
    assert result["gtg_ms"] is None
    for row in result["transitions"]:
        if row["sampling_bounds_ms"]:
            low, high = row["sampling_bounds_ms"]
            assert low <= row["optical_10_90_ms"] <= high

def test_no_camera_and_connection_loss(monkeypatch):
    monkeypatch.setattr(server.glob, "glob", lambda _: [])
    with ThreadingHTTPServer(("127.0.0.1", 0), server.Handler) as http:
        http.agent = server.Agent()
        worker = threading.Thread(target=http.serve_forever, daemon=True)
        worker.start()
        client = AgentClient("127.0.0.1")
        client.base = f"http://127.0.0.1:{http.server_port}"
        try:
            assert client.request("/health")["cameras"] == []
            with pytest.raises(AgentError, match="Camera not found"):
                client.request("/preview", {"device":"/dev/video0","resolution":"640x480",
                    "fps":30,"format":"MJPG","exposure":0,"gain":0,"roi":[.1,.1,.8,.8]})
        finally:
            http.shutdown()
            worker.join()
    with pytest.raises(AgentError, match="Связь с агентом недоступна"):
        client.request("/health")

class FakeSerial:
    def __init__(self, **kwargs):
        self.reply = None
        self.closed = False

    def write(self, raw):
        message = json.loads(raw)
        reply = {"id":message["id"], "data":{"protocol":"display-response-usb","version":1,
                                              "operation":message["operation"], **message["data"]}}
        self.reply = io.BytesIO(b"boot log\n" + json.dumps(reply).encode()+b"\n")

    def read_until(self, expected, size):
        return self.reply.readline(size)

    def close(self):
        self.closed = True

def test_usb_protocol():
    with EspUsbClient("COM7", serial_factory=FakeSerial) as client:
        assert client.health()["version"] == 1
        assert client.read_samples("s", 4, 32)["offset"] == 4
        with pytest.raises(ValueError):
            client.read_samples("s", 0, 900)
    assert client.serial.closed

def test_report_formats(qt, tmp_path):
    options = dict(DEFAULTS, camera_fps=30, hold=.5, repeats=2)
    samples = simulate(options)
    hardware = {"simulation":True,"options":options,"samples":samples,
                "analysis":analyze(samples,.5,True),"pc_events":[],"camera":{}}
    report = report_data({"Model":{"source":"EDID","value":"Example & monitor"}}, "fake",hardware)
    for kind in ("json","csv","html","pdf"):
        path = tmp_path/f"report.{kind}"
        export(path,report)
        assert path.stat().st_size > 100
    assert json.loads((tmp_path/"report.json").read_text(encoding="utf-8"))["hardware"]["simulation"]
    assert "simulation" in (tmp_path/"report.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    html = (tmp_path/"report.html").read_text(encoding="utf-8")
    assert "image/png;base64" in html and "Example &amp; monitor" in html
    assert (tmp_path/"report.pdf").read_bytes().startswith(b"%PDF")
