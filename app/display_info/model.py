import json
import math

from app.utils.settings import RESOURCES

UNKNOWN = "Не определено"
GRAY_LEVELS = (0, 32, 64, 96, 128, 160, 192, 224, 255)
PANELS = ("Неизвестно", "TN", "IPS", "VA", "OLED", "QD-OLED", "Другая")

def metric(value=None, source=None):
    return {"value": value if value is not None and value != "" else UNKNOWN,
            "source": source if value is not None and value != "" else UNKNOWN}

def parse_edid(raw):
    if len(raw) < 128 or raw[:8] != bytes.fromhex("00 ff ff ff ff ff ff 00") or sum(raw[:128]) % 256:
        return {}
    code = int.from_bytes(raw[8:10], "big")
    letters = [(code >> shift) & 31 for shift in (10, 5, 0)]
    vendor = "".join(chr(64 + letter) for letter in letters) if all(1 <= n <= 26 for n in letters) else None
    serial = int.from_bytes(raw[12:16], "little")
    result = {"vendor": vendor, "serial": str(serial) if serial not in (0, 0xffffffff) else None,
              "product": f"{int.from_bytes(raw[10:12], 'little'):04X}"}
    hdmi_hdr = False
    extensions_valid = len(raw) >= (1 + raw[126]) * 128
    for offset in range(128, min(len(raw), (1 + raw[126]) * 128), 128):
        block = raw[offset:offset + 128]
        if len(block) != 128 or sum(block) % 256:
            extensions_valid = False
            continue
        if block[0] != 2 or not 4 <= block[2] <= 127:
            continue
        index = 4
        while index < block[2]:
            tag, length = block[index] >> 5, block[index] & 31
            end = index + 1 + length
            if end > block[2]:
                break
            payload = block[index + 1:end]
            if tag == 7 and length >= 3 and payload[0] == 6 and payload[1] & 0x0c:
                hdmi_hdr = True
            if tag == 3 and length >= 8:
                forum = payload[:3] == bytes.fromhex("d8 5d c4")
                if forum and payload[7] & 2:
                    result["allm"] = True
                if forum and length >= 10:
                    low, high = payload[8] & 63, ((payload[8] & 192) << 2) | payload[9]
                    if low and high >= low:
                        result["vrr"] = [low, high]
            index = end
    if hdmi_hdr and extensions_valid:
        result["hdr"] = True
    if raw[21] and raw[22]:
        result["size"] = [raw[21] * 10, raw[22] * 10]
    for offset in (54, 72, 90, 108):
        descriptor = raw[offset:offset + 18]
        if descriptor[:2] != b"\0\0":
            if offset == 54 and raw[24] & 2:
                physical = [descriptor[12] | ((descriptor[14] & 0xf0) << 4),
                            descriptor[13] | ((descriptor[14] & 0x0f) << 8)]
                if all(physical):
                    result["size"] = physical
                    result["size_detail"] = "EDID, физический размер предпочтительного тайминга"
                result["preferred"] = [
                    descriptor[2] | ((descriptor[4] & 0xf0) << 4),
                    descriptor[5] | ((descriptor[7] & 0xf0) << 4),
                ]
            continue
        key = {252: "name", 255: "serial"}.get(descriptor[3])
        if key:
            result[key] = descriptor[5:].split(b"\n")[0].decode("ascii", "replace").strip("\0 ")
    return result

def resolve_screen(screens, name, origin=None, model=None):
    exact = [screen for screen in screens if screen.name().casefold() == name.casefold()]
    if len(exact) == 1:
        return exact[0]
    # On Windows Qt leaves the native desktop origins intact when scaling screen sizes.
    if origin is not None:
        by_position = [screen for screen in screens if
                       [screen.geometry().x(), screen.geometry().y()] == list(origin)]
        if len(by_position) == 1:
            return by_position[0]
    if model:
        by_model = [screen for screen in screens if screen.model().casefold() == model.casefold()]
        if len(by_model) == 1:
            return by_model[0]
    return None

def rows(record, override=None, catalog=None):
    override = override or {}
    if catalog is None:
        try:
            catalog = json.loads((RESOURCES / "config/panels.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            catalog = {}
    edid = parse_edid(record.get("edid", b""))
    model = edid.get("name") or record.get("name")
    entry = catalog.get(f"{edid.get('vendor')}:{edid.get('product')}", {})
    win = record.get("source", "Windows API")
    ed = "EDID"
    res = {}
    res["Производитель"] = metric(entry["manufacturer"], "Локальная база") if entry.get("manufacturer") else metric(edid.get("vendor"), ed)
    res["Модель"] = metric(entry["model"], "Локальная база") if entry.get("model") else metric(model, ed if edid.get("name") else win)
    res["Имя устройства из EDID"] = metric(edid.get("name"), ed)
    res["Спецификация модели"] = metric(entry.get("source"), "Локальная база")
    res["Серийный номер"] = metric(edid.get("serial"), ed)
    res["Идентификатор"] = metric(record.get("id"), win)
    for label, field in (
        ("Подключение", "connection"), ("Разрешение рабочего стола", "desktop"),
        ("Активное разрешение сигнала", "active"), ("Полный размер сигнала с гашением", "total"),
        ("Частота обновления, Гц", "hz"), ("Частота сигнала, Гц", "signal_hz"),
        ("Строчная частота, Гц", "horizontal_hz"), ("Пиксельная частота, Гц", "pixel_clock"),
        ("Бит на канал", "bits"), ("Кодирование цвета", "encoding"),
        ("SDR / WCG / HDR Windows", "hdr_mode"), ("HDR доступен по текущему видеотракту", "hdr_supported"),
        ("HDR включён в настройках Windows", "hdr_enabled"),
    ):
        res[label] = metric(record.get(field), win)
    res["Графический адаптер"] = metric(record.get("gpu"), "Реестр Windows")
    res["Версия драйвера"] = metric(record.get("driver"), "Реестр Windows")
    res["Текущий видеорежим"] = metric(
        f"{record['active'][0]}×{record['active'][1]} @ {record['signal_hz']:.3f} Гц"
        if record.get("active") and record.get("signal_hz") else None, win)
    modes = record.get("modes", [])
    res["Доступные режимы (Ш × В @ Гц, bpp)"] = metric(
        ", ".join(f"{w}×{h} @ {hz or '?'} ({bits})" for w,h,hz,bits in modes) or None, win)
    res["Доступные разрешения"] = metric(", ".join(
        f"{w}×{h}" for w,h in sorted({m[:2] for m in modes})) or None, win)
    res["Доступные частоты, Гц"] = metric(sorted({m[2] for m in modes if m[2]}) or None, win)
    res["Предпочтительное разрешение"] = metric(edid.get("preferred"), ed)
    size = edid.get("size")
    res["Размеры, мм"] = metric(size, edid.get("size_detail", ed))
    res["Диагональ, дюймы"] = metric(round(math.hypot(*size) / 25.4, 2) if size else None, "Рассчитано из EDID")
    hz = record.get("hz")
    res["Период кадра, мс"] = metric(round(1000 / hz, 4) if hz else None, f"Рассчитано из частоты • {win}")
    for label, key in (("Тип матрицы", "panel"), ("Подсветка", "backlight"), ("Заявленный GtG, мс", "gtg_ms")):
        res[label] = metric(override[key], "Ручной ввод") if override.get(key) else metric(entry.get(key), "Локальная база")
    res["HDR поддерживается дисплеем"] = metric(edid.get("hdr"), ed)
    res["HDMI VRR поддерживается дисплеем"] = metric(True if edid.get("vrr") else None, ed)
    res["Диапазон HDMI VRR, Гц"] = metric(edid.get("vrr"), ed)
    res["ALLM поддерживается дисплеем"] = metric(edid.get("allm"), ed)
    for key, flag in (("Adaptive Sync заявлен для модели", "adaptive_sync"),
                      ("AMD FreeSync заявлен для модели", "freesync"),
                      ("NVIDIA G-SYNC заявлен для модели", "gsync_advertised")):
        res[key] = metric(entry.get(flag), "Локальная база")
    for key in ("Сертификация G-SYNC / G-SYNC Compatible",
                "VRR доступен через драйвер", "VRR включён в системе", "VRR активен во время теста",
                "ALLM активен", "HGiG", "Аппаратный GtG", "Задержка HDMI-to-light",
                "Программная оценка движения"):
        res[key] = metric()
    res["VSync генератора"] = metric("Управление недоступно (Qt Widgets)", "Приложение")
    priority = ("Производитель", "Модель", "Тип матрицы", "Подсветка", "Подключение",
                "Активное разрешение сигнала", "Частота обновления, Гц", "Период кадра, мс",
                "Бит на канал", "Кодирование цвета", "SDR / WCG / HDR Windows",
                "Графический адаптер", "Версия драйвера", "Заявленный GtG, мс")
    return {**{key:res[key] for key in priority}, **res}

def text_value(value):
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, list):
        return " × ".join(map(str, value)) if len(value) == 2 else ", ".join(map(str, value))
    return str(value)
