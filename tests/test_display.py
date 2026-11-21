import sys

import pytest
from PySide6.QtCore import QRect

from app.display_info.model import UNKNOWN, parse_edid, resolve_screen, rows
from app.display_info.windows import read_windows

def edid():
    data = bytearray(128)
    data[:8] = bytes.fromhex("00 ff ff ff ff ff ff 00")
    data[8:10] = ((19 << 10) | (11 << 5) | 7).to_bytes(2, "big")
    data[10:12] = bytes.fromhex("1834")
    data[21:23] = bytes([77,39])
    data[24] = 2
    data[54:72] = bytes.fromhex("4d7d70a0d0a02d50302035001d4e3100001a")
    data[90:108] = bytes.fromhex("000000fc00474d3334564730310a20202020")
    data[-1] = -sum(data) % 256
    return data

def test_edid_record():
    parsed = parse_edid(edid())
    assert parsed["vendor"] == "SKG"
    assert parsed["product"] == "3418"
    assert parsed["preferred"] == [3440,1440]
    assert parsed["name"] == "GM34VG01"
    assert parsed["size"] == [797,334]
    display = rows({"edid": edid(), "hz": 60, "connection": "HDMI"}, {"panel":"IPS"})
    assert display["Период кадра, мс"]["value"] == pytest.approx(16.6667)
    assert display["Тип матрицы"]["source"] == "Ручной ввод"
    assert display["VRR активен во время теста"]["value"] == UNKNOWN
    assert display["Заявленный GtG, мс"]["value"] == 5

def test_no_edid():
    assert parse_edid(b"") == {}
    corrupted = edid()
    corrupted[25] ^= 1
    assert not parse_edid(corrupted)
    display = rows({"name":"Windows monitor", "hz":50})
    assert display["Серийный номер"]["value"] == UNKNOWN
    assert display["Модель"]["source"] == "Windows API"
    assert display["Период кадра, мс"]["value"] == 20

class Screen:
    def __init__(self, name, x):
        self.label, self.x = name, x

    def name(self):
        return self.label

    def model(self):
        return self.label

    def geometry(self):
        return QRect(self.x, 0, 960, 540)

def test_resolve_extended_multimonitor():
    s1, s2 = Screen("Same Monitor", 0), Screen("Same Monitor", -1920)
    assert resolve_screen([s1, s2], r"\\.\DISPLAY2", [-1920, 0], "Same Monitor") is s2
    assert resolve_screen([s1, s2], "Same Monitor", [0, 0], "Same Monitor") is s1
    assert resolve_screen([s1, s2], r"\\.\DISPLAY3", [900, 0], "Same Monitor") is None

@pytest.mark.skipif(sys.platform != "win32", reason="Windows CCD")
def test_live_windows(qt):
    items = read_windows()
    if not items:
        pytest.skip("Windows session has no active CCD paths")
    for item in items:
        assert item["id"]
        assert item["hz"] is None or item["hz"] > 0
    assert any(resolve_screen(qt.screens(), item["screen"], item["origin"], item["name"]) for item in items)
