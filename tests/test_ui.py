from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest

from app.gui.main_window import MainWindow
from app.slideshow.view import Slideshow, scan
from app.software_tests.motion import MODES, Motion, frame_stats
from app.utils.settings import DEFAULTS, ROOT, Settings

def wait_until(predicate, limit=8000):
    elapsed = 0
    while not predicate():
        assert elapsed < limit, "Qt condition timed out"
        QTest.qWait(25)
        elapsed += 25

def tap(widget, key):
    QTest.keyClick(widget, key)
    QTest.qWait(20)

def test_slideshow_keyboard_and_limits(qt, tmp_path):
    for name in ("z.jpg", "A.png"):
        img = QImage(123, 87, QImage.Format.Format_RGB32)
        img.fill(QColor("blue"))
        assert img.save(str(tmp_path/name))
    (tmp_path/"ignore.gif").touch()
    paths = scan(tmp_path)
    assert [p.name for p in paths] == ["A.png", "z.jpg"]
    show = Slideshow(paths, 3, "Fit", True)
    show.launch(qt.primaryScreen())
    QTest.qWait(30)
    assert show.isFullScreen()
    assert show.screen() == qt.primaryScreen()
    tap(show, Qt.Key.Key_Left)
    assert show.index == 1
    tap(show, Qt.Key.Key_Right)
    assert show.index == 0
    assert show.timer.remainingTime() > 2500
    for key in (Qt.Key.Key_Plus, Qt.Key.Key_Up, Qt.Key.Key_Up):
        tap(show, key)
    assert show.interval == 5
    for _ in range(7):
        tap(show, Qt.Key.Key_Minus)
    assert show.interval == 1
    tap(show, Qt.Key.Key_Down)
    assert show.interval == 1
    tap(show, Qt.Key.Key_Space)
    assert not show.playing and not show.timer.isActive()
    tap(show, Qt.Key.Key_Right)
    assert not show.timer.isActive()
    tap(show, Qt.Key.Key_Space)
    assert show.timer.isActive()
    QTest.qWait(1100)
    assert show.index == 0
    tap(show, Qt.Key.Key_Escape)

def test_frame_stats():
    stats = frame_stats([8,10,12,10])
    assert stats == dict(fps=100, mean_ms=10, jitter_ms=1.414, p95_ms=12, max_ms=12, samples=4)
    assert not frame_stats([])

def test_motion_modes_and_fullscreen(qt):
    for name in MODES:
        options = dict(DEFAULTS, motion=name, fps=90)
        motion = Motion(options)
        stats = []
        motion.stats_ready.connect(stats.append)
        motion.launch(qt.primaryScreen())
        QTest.qWait(115)
        assert motion.isFullScreen()
        if motion.sprite:
            assert motion.sprite.isValid()
        assert not motion.grab().isNull()
        tap(motion, Qt.Key.Key_Escape)
        assert stats[-1]["fps"] > 0

def test_integrated_real_images_latency_simulation_and_report(qt, tmp_path):
    settings = Settings(tmp_path/"settings.json")
    settings["report_path"] = str(tmp_path)
    window = MainWindow(settings)
    window.show()
    wait_until(lambda: not window.refreshing)
    assert window.selected_screen() in qt.screens()
    assert window.display_data["Частота обновления, Гц"]["value"] != "Не определено"
    if scan(ROOT / "Images"):
        window.tabs.setCurrentIndex(1)
        window.open_slide()
        QTest.qWait(100)
        slide = window.slide
        assert slide.isFullScreen() and not slide.image.isNull()
        tap(slide, Qt.Key.Key_Right)
        if len(slide.files) > 1:
            assert slide.index == 1
        tap(slide, Qt.Key.Key_Escape)
        wait_until(lambda: window.active is None)
    window.tabs.setCurrentIndex(2)
    window.motion_options["motion"].setCurrentText("Software Latency")
    window.open_motion()
    QTest.qWait(100)
    latency = window.active
    assert latency.isFullScreen() and latency.screen() == window.selected_screen()
    initial_speed = latency.speed
    tap(latency, Qt.Key.Key_Right)
    tap(latency, Qt.Key.Key_Up)
    assert latency.color_index == 1 and latency.speed > initial_speed
    tap(latency, Qt.Key.Key_Down)
    tap(latency, Qt.Key.Key_Left)
    assert latency.color_index == 0 and latency.speed == initial_speed
    wait_until(lambda: bool(latency.live_stats.get("fps")))
    tap(latency, Qt.Key.Key_Escape)
    wait_until(lambda: bool(window.current_report()["motion"]))
    result = window.current_report()["motion"][-1]["statistics"]
    assert result["samples"] > 0 and result["p95_ms"] > 0
    assert result["speed_px_s"] == initial_speed and result["square_color"] == "#ffffff"
    window.tabs.setCurrentIndex(3)
    hardware = window.hardware
    hardware.controls["hold"].setValue(.25)
    hardware.controls["repeats"].setValue(2)
    hardware.preview()
    assert not hardware.preview_view.image.isNull()
    hardware.start()
    wait_until(lambda: bool(window.current_report()["hardware"]), 6000)
    result = window.current_report()["hardware"]
    assert result["simulation"] and result["completed"] and len(result["pc_events"]) == 5
    assert len(result["analysis"]["transitions"]) >= 2
    assert len(hardware.chart.samples) > 0
    wait_until(lambda: bool(list(tmp_path.glob("measurement-*.json"))))
    window.close()
