import base64
import csv
import html
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QImage, QPainter, QPageSize, QPdfWriter, QTextDocument

from app.hardware_tests.views import draw_chart
from app.display_info.model import text_value

CSV_FIELDS = ("frame", "time_ns", "mean", "min", "max", "gap", "read_ns", "process_ns")

def write_json(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)

def report_data(display, display_id, hardware=None, motion=None, conditions=""):
    return {"application": "Display Response Tester V1.2", "schema": 1,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "display_id": display_id, "display": display, "motion": motion or [],
            "hardware": hardware, "conditions": conditions}

def chart_image(samples, simulation):
    image = QImage(720, 240, QImage.Format.Format_RGB32)
    with QPainter(image) as painter:
        draw_chart(painter, QRectF(image.rect()), samples, simulation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.data()).decode("ascii")

def escape(value):
    return html.escape(text_value(value))

def table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table cellspacing="0" cellpadding="5" width="100%"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

def pretty(value):
    return "<pre>" + html.escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"

def make_html(report, display_only=False):
    title = escape(report["application"])
    body = f"<h1>{title}</h1><p>{escape(report['created'])}</p>"
    if report["conditions"]:
        body += f"<h2>Условия тестирования</h2><p>{escape(report['conditions'])}</p>"
    body += "<h2>Дисплей</h2>" + table(
        ("Параметр", "Значение", "Источник"),
        ((key, row["value"], row["source"]) for key,row in report["display"].items()))
    if not display_only:
        body += test_sections(report)
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;color:#17263a}}
h1,h2,h3{{color:#132e4f}} th{{background:#dce8f3;text-align:left}}
td{{border-bottom:1px solid #d9e1ea;overflow-wrap:anywhere}} pre{{white-space:pre-wrap;font-size:10pt}}</style>
<body>{body}</body></html>'''

def test_sections(report):
    body = "<h2>Motion Test</h2>"
    if report["motion"]:
        body += "<p>FPS и интервалы вызовов paintEvent. Источник — программное измерение генератора.</p>"
        for run in report["motion"]:
            body += f"<h3>{escape(run['mode'])}</h3>" + pretty(run)
    else:
        body += "<p>Результатов нет.</p>"
    body += "<h2>Hardware Test</h2>"
    hardware = report["hardware"]
    if hardware:
        analysis = hardware["analysis"]
        label = ("SIMULATION — синтетические данные" if hardware["simulation"] else
                 "Физически зарегистрированные коды камеры; времена переходов рассчитаны")
        body += f"<p><b>{label}</b></p>"
        samples = hardware["samples"]
        if len(samples) > 1:
            image = chart_image(samples, hardware["simulation"])
            body += f'<p><img width="650" height="217" src="data:image/png;base64,{image}"></p>'
        body += table(("Направление", "Обнаружено, с", "10–90%, мс", "Границы дискретизации, мс", "Стабилизация, мс"),
                      ((row["direction"], row["detected_s"], row["optical_10_90_ms"] or "—",
                        row["sampling_bounds_ms"] or "—",row["stabilization_ms"] or "—") for row in analysis["transitions"]))
        body += "<h3>Методика, качество и настройки</h3>" + pretty({
            **{key: value for key, value in analysis.items() if key != "transitions"},
            **{key: hardware.get(key) for key in ("options", "camera", "pc_events", "network_rtt_ms", "completed", "error")},
        })
        body += "<p>Временные шкалы ПК и агента независимы. RTT включает работу агента и передачу данных. Односторонняя задержка Ethernet и задержка HDMI-to-light не определены.</p>"
    else:
        body += "<p>Результатов нет.</p>"
    return body

def make_display_txt(report):
    lines = [report["application"], report["created"], "", "Параметр\tЗначение\tИсточник"]
    lines.extend(f"{key}\t{text_value(row['value'])}\t{row['source']}"
                 for key, row in report["display"].items())
    return "\n".join(lines) + "\n"

def export(path, report, display_only=False):
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".json":
        write_json(path, report)
    elif ext == ".csv":
        hw = report.get("hardware")
        if not hw:
            raise ValueError("Для CSV требуется аппаратный или синтетический временной ряд.")
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("simulation", *CSV_FIELDS), extrasaction="ignore")
            writer.writeheader()
            writer.writerows({"simulation": hw["simulation"], **item} for item in hw["samples"])
    elif ext == ".txt":
        path.write_text(make_display_txt(report), encoding="utf-8-sig")
    elif ext == ".html":
        path.write_text(make_html(report, display_only), encoding="utf-8")
    elif ext == ".pdf":
        doc = QTextDocument()
        doc.setHtml(make_html(report, display_only))
        pdf = QPdfWriter(str(path))
        pdf.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        pdf.setResolution(96)
        pdf.setTitle(report["application"])
        doc.print_(pdf)
        del pdf
        if not path.is_file() or path.stat().st_size < 100:
            raise OSError("Не удалось записать PDF.")
    else:
        raise ValueError("Форматы экспорта: TXT, HTML, PDF, JSON, CSV.")
