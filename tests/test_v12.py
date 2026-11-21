from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from app.gui.main_window import COPYABLE_DISPLAY_VALUES, MainWindow
from app.software_tests.latency import reflected_position
from app.software_tests.patterns import GRAY_PATTERNS, Transitions
from app.utils.settings import DEFAULTS, Settings

def test_reflection():
    assert [reflected_position(x, 10) for x in (-3, 0, 5, 10, 13, 20)] == [3,0,5,10,7,0]
    assert reflected_position(99, 0) == 0

def gray_at(image, x, y):
    scale = image.devicePixelRatio()
    return image.pixelColor(round(x*scale), round(y*scale)).red()

def test_new_gray_patterns(qt):
    window = Transitions(dict(DEFAULTS, motion="Gray-to-Gray Patterns"))
    window.resize(720,400)
    window.index = GRAY_PATTERNS.index("Тени и света")
    dark_light = window.grab().toImage()
    assert gray_at(dark_light,60,20) < 17
    assert gray_at(dark_light,60,220) >= 239
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert GRAY_PATTERNS[window.index] == "Радиальные шкалы"
    radial = window.grab().toImage()
    assert gray_at(radial,180,200) > 245
    assert gray_at(radial,540,200) == 255
    assert gray_at(radial,1,1) == 0
    window.close()

def test_display_clipboard_and_exports(qt, tmp_path, monkeypatch):
    settings = Settings(tmp_path/"settings.json")
    settings["report_path"] = str(tmp_path)
    saved = []
    monkeypatch.setattr(QApplication,"clipboard",lambda: SimpleNamespace(setText=saved.append))
    device = {"id":"dummy", "screen":qt.primaryScreen().name(), "name":"Acme <Display>"}
    window = MainWindow(settings, lambda: [device])
    window.show()
    for _ in range(50):
        if not window.refreshing:
            break
        QTest.qWait(25)
    assert not window.refreshing
    for row in range(window.info.rowCount()):
        if window.info.item(row,0).text() in COPYABLE_DISPLAY_VALUES:
            cell = window.info.item(row,0)
            window.info.scrollToItem(cell)
            QTest.mouseClick(window.info.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.info.visualItemRect(cell).center())
            assert saved[-1] == window.info.item(row,1).text()
    assert len(saved) == 3
    export_button = next(btn for btn in window.findChildren(QPushButton) if btn.text() == "Экспорт TXT / HTML")
    for extension in ("txt","html"):
        def filename(*args):
            assert "TXT (*.txt);;HTML (*.html)" == args[-1]
            return str(tmp_path/"selected-display"), f"{extension.upper()} (*.{extension})"
        monkeypatch.setattr(QFileDialog,"getSaveFileName",filename)
        export_button.click()
        output = tmp_path/f"selected-display.{extension}"
        for _ in range(50):
            if output.exists() and output.stat().st_size > 100:
                break
            QTest.qWait(25)
        result = output.read_text(encoding="utf-8-sig")
        assert "Motion Test" not in result
        assert ("Acme &lt;Display&gt;" if extension=="html" else "Acme <Display>") in result
        assert "Источник" in result
    window.close()
