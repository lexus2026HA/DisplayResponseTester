import json
import logging
import sys
from pathlib import Path

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
RESOURCES = Path(getattr(sys, "_MEIPASS", ROOT))
DEFAULTS = {
    "display": "", "interval": 3, "fit": "Fit", "overlay": False,
    "motion_fullscreen": True, "usb_port": "",
    "motion": "Pepper", "speed": 480, "fps": 120, "background": "#777777",
    "count": 3, "lanes": 1, "size": 110, "direction": "→", "rpm": 480,
    "hold": 1.0, "gray_from": 32, "gray_to": 224, "host": "",
    "simulation": True, "camera": "", "camera_fps": 30, "camera_format": "MJPG",
    "resolution": "640x480", "exposure": 0, "gain": 0, "repeats": 4,
    "roi": [0.4, 0.4, 0.2, 0.2], "report_path": "", "theme": "Dark", "overrides": {},
}

class Settings(dict):
    def __init__(self, path=ROOT / "config/settings.json"):
        super().__init__(DEFAULTS)
        self["overrides"] = {}
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            self.update({key: value for key, value in data.items()
                         if key in DEFAULTS and isinstance(value, type(DEFAULTS[key]))})
        except (OSError, ValueError, AttributeError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            logging.exception("Unable to save settings")
