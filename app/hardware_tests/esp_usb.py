"""USB CDC bridge for the future ESP32-C3 optical backend."""
import json
import time

import serial
from serial.tools.list_ports import comports

from app.hardware_tests.client import AgentError

MAX_LINE = 2 * 1024 * 1024

def ports():
    return [(item.device, item.description) for item in comports()]

class EspUsbClient:
    def __init__(self, port, baudrate=115200, timeout=5, serial_factory=serial.Serial):
        self.timeout = timeout
        self.rtt_ms = None
        self.sequence = 0
        try:
            self.serial = serial_factory(port=port, baudrate=baudrate, timeout=.25, write_timeout=2)
        except (OSError, ValueError) as error:
            raise AgentError(f"USB {port}: {error}") from error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.serial.close()

    def health(self):
        info = self.request("health")
        if info.get("protocol") != "display-response-usb" or info.get("version") != 1:
            raise AgentError("Ответила несовместимая прошивка ESP32-C3.")
        return info

    def start_capture(self, duration_ms, sample_hz):
        return self.request("start", {"duration_ms": duration_ms, "sample_hz": sample_hz})

    def status(self, session):
        return self.request("status", {"session": session})

    def stop_capture(self, session):
        return self.request("stop", {"session": session})

    def read_samples(self, session, offset=0, count=256):
        if offset < 0 or not 1 <= count <= 512:
            raise ValueError("USB sample page out of range")
        return self.request("samples", {"session": session, "offset": offset, "count": count})

    def request(self, path, payload=None):
        self.sequence += 1
        number = self.sequence
        message = {"id": number, "operation": path.lstrip("/"), "data": payload or {}}
        started = time.monotonic()
        try:
            self.serial.write(json.dumps(message, allow_nan=False).encode("utf-8") + b"\n")
            line = bytearray()
            while time.monotonic() - started < self.timeout:
                part = self.serial.read_until(b"\n", MAX_LINE-len(line))
                line.extend(part)
                if len(line) >= MAX_LINE:
                    raise AgentError("Превышен размер сообщения USB.")
                if not part.endswith(b"\n"):
                    continue
                try:
                    reply = json.loads(line)
                except (ValueError, UnicodeError):
                    line.clear()
                    continue
                line.clear()
                if not isinstance(reply, dict) or reply.get("id") != number:
                    continue
                self.rtt_ms = round((time.monotonic()-started)*1000, 2)
                if "error" in reply:
                    raise AgentError(str(reply["error"]))
                if not isinstance(reply.get("data"), dict):
                    raise AgentError("Неизвестный формат ответа ESP32-C3.")
                return reply["data"]
        except OSError as error:
            raise AgentError(f"Связь с USB-тестером потеряна: {error}") from error
        raise AgentError("ESP32-C3 не ответил на команду. Проверьте COM-порт и совместимость прошивки.")
