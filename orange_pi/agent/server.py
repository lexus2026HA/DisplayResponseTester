import argparse
import base64
import glob
import json
import logging
import math
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple

import cv2

DEVICE_PATH = re.compile(r"/dev/video[0-9]+")

def command(device, *args):
    try:
        completed = subprocess.run(["v4l2-ctl", "-d", device, *args], capture_output=True,
                                   text=True, timeout=2, check=True)
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        logging.debug("v4l2-ctl %s: %s", args, error)
        return ""

def cameras():
    items = []
    for path in sorted(glob.glob("/dev/video[0-9]*")):
        if not DEVICE_PATH.fullmatch(path):
            continue
        modes = command(path, "--list-formats-ext")
        if modes:
            items.append({"device": path, "modes": modes,
                          "controls": command(path, "--list-ctrls-menus"),
                          "driver": command(path, "--info")})
    return items

class CameraConfig(NamedTuple):
    device: str
    width: int
    height: int
    fps: float
    format: str
    exposure: int
    gain: int
    roi: tuple

    @classmethod
    def parse(cls, body):
        device = body.get("device", "")
        width, height = map(int, body["resolution"].lower().split("x"))
        fps = float(body["fps"])
        fmt = body["format"].upper()
        exposure, gain = int(body["exposure"]), int(body["gain"])
        roi = tuple(map(float, body["roi"]))
        if not DEVICE_PATH.fullmatch(device) or not 16 <= width <= 4096 or not 16 <= height <= 4096:
            raise ValueError("Invalid camera device or dimensions")
        if not 1 <= fps <= 240 or not re.fullmatch(r"[A-Z0-9]{4}", fmt):
            raise ValueError("Invalid FPS or FourCC")
        if len(roi) != 4 or any(not 0 <= v <= 1 for v in roi):
            raise ValueError("Invalid ROI")
        x, y, w, h = roi
        if w <= 0 or h <= 0 or x+w > 1.000001 or y+h > 1.000001:
            raise ValueError("ROI outside frame")
        return cls(device, width, height, fps, fmt, exposure, gain, roi)

def open_camera(config):
    if not glob.glob(config.device):
        raise ValueError("Camera not found")
    cap = cv2.VideoCapture(config.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        raise ValueError("Camera unavailable")
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.format))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
        cap.set(cv2.CAP_PROP_FPS, config.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        reported = command(config.device, "--list-ctrls")
        controls = re.findall(r"^\s*(\w+)\s+0x[0-9a-f]+", reported, re.M)
        auto = next((name for name in ("auto_exposure", "exposure_auto") if name in controls), None)
        exp = next((name for name in ("exposure_time_absolute", "exposure_absolute") if name in controls), None)
        if auto:
            command(config.device, f"--set-ctrl={auto}=1")
        if exp and config.exposure > 0:
            command(config.device, f"--set-ctrl={exp}={config.exposure}")
        if "gain" in controls:
            command(config.device, f"--set-ctrl=gain={config.gain}")
        actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        actual = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                  "fps": cap.get(cv2.CAP_PROP_FPS), "format": "".join(chr((actual_fourcc >> (8*i)) & 255) for i in range(4)),
                  "controls": command(config.device, "--list-ctrls"), "device": config.device,
                  "roi_normalized": config.roi, "timing": "OpenCV read completion"}
        return cap, actual
    except BaseException:
        cap.release()
        raise

def preview(config):
    cap, camera = open_camera(config)
    try:
        frame = None
        for _ in range(4):
            ok, frame = cap.read()
            if not ok:
                raise ValueError("Camera did not deliver a frame")
        h, w = frame.shape[:2]
        if w > 640:
            frame = cv2.resize(frame, (640, max(1, round(h*640/w))), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise ValueError("Unable to encode preview")
        return {"camera": camera, "jpeg": base64.b64encode(jpeg).decode("ascii")}
    finally:
        cap.release()

class Capture:
    def __init__(self, config, duration):
        self.id = uuid.uuid4().hex
        self.config = config
        self.duration = duration
        self.camera = {}
        self.samples = []
        self.stop = threading.Event()
        self.state = "starting"
        self.error = ""
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def run(self):
        cap = None
        try:
            cap, self.camera = open_camera(self.config)
            fps = self.camera["fps"] or self.config.fps
            period = 1e9 / fps
            deadline = time.monotonic() + self.duration
            previous = None
            errors = 0
            while time.monotonic() < deadline and not self.stop.is_set():
                start = time.monotonic_ns()
                ok, frame = cap.read()
                stamp = time.monotonic_ns()
                if not ok:
                    errors += 1
                    if errors >= 5:
                        raise ValueError("Camera feed lost")
                    self.stop.wait(.01)
                    continue
                h, w = frame.shape[:2]
                x, y, rw, rh = self.config.roi
                left, top = min(w-1, int(x*w)), min(h-1, int(y*h))
                right, bottom = max(left+1, int((x+rw)*w)), max(top+1, int((y+rh)*h))
                region = frame[top:bottom, left:right]
                gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
                low, high, _, _ = cv2.minMaxLoc(gray)
                mean = cv2.mean(gray)[0]
                self.samples.append({"frame": len(self.samples), "time_ns": stamp, "mean": mean,
                                     "min": low, "max": high,
                                     "gap": bool(errors or previous is not None and stamp-previous > period*1.65),
                                     "read_ns": stamp-start, "process_ns": time.monotonic_ns()-stamp})
                self.state = "recording"
                errors = 0
                previous = stamp
        except Exception as error:
            self.error = str(error)
            logging.exception("Capture %s failed", self.id)
        finally:
            if cap is not None:
                cap.release()
            self.state = "error" if self.error else "done"
            logging.info("Capture %s finished with %s frames (%s)", self.id, len(self.samples), self.state)

class Agent:
    def __init__(self):
        self.lock = threading.Lock()
        self.capture = None

    def handle(self, method, path, data):
        if method == "GET" and path == "/health":
            return {"agent": "DisplayResponseAgent", "version": 1, "cameras": cameras()}
        with self.lock:
            active = self.capture and self.capture.worker.is_alive()
            if method == "POST" and path == "/preview":
                if active:
                    raise ValueError("Camera is recording")
                return preview(CameraConfig.parse(data))
            if method == "POST" and path == "/start":
                if active:
                    raise ValueError("Camera is already recording")
                duration = float(data["duration"])
                if not math.isfinite(duration) or not 1 <= duration <= 300:
                    raise ValueError("Capture duration must be 1–300 seconds")
                self.capture = Capture(CameraConfig.parse(data), duration)
                return {"id": self.capture.id}
            if method == "POST" and path in ("/status", "/stop"):
                capture = self.capture
                if not capture or data["id"] != capture.id:
                    raise ValueError("Unknown capture session")
                if path == "/stop":
                    capture.stop.set()
                state = capture.state
                result = {"state": state, "frame_count": len(capture.samples),
                          "error": capture.error, "camera": capture.camera}
                if state in ("done", "error"):
                    result["samples"] = capture.samples
                return result
        raise ValueError("Unknown API route")

class Handler(BaseHTTPRequestHandler):
    def response(self, method):
        try:
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid payload size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected JSON object")
            result, code = self.server.agent.handle(method, self.path, body), 200
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            result, code = {"error": str(error)}, 400
        except Exception:
            logging.exception("Agent request failed")
            result, code = {"error": "Capture backend error, see agent journal"}, 500
        raw = json.dumps(result, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (ConnectionError, TimeoutError):
            pass

    def do_GET(self):
        self.response("GET")

    def do_POST(self):
        self.response("POST")

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        logging.info("%s %s", self.client_address[0], fmt % args)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with ThreadingHTTPServer((args.bind, args.port), Handler) as server:
        server.agent = Agent()
        logging.info("DisplayResponseAgent listening on %s:%d", args.bind, args.port)
        server.serve_forever()

if __name__ == "__main__":
    main()
