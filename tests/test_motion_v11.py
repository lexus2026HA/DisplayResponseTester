from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.software_tests.motion import FOUR_LANES, LANE_RATIOS, SQUARE_MODES, Motion
from app.software_tests.patterns import COLORS, GRAY_PATTERNS, Transitions
from app.utils.settings import DEFAULTS

def test_color_keys_and_autoplay(qt):
    window = Transitions(dict(DEFAULTS, motion="Color Transitions", hold=.25))
    window.launch(qt.primaryScreen())
    QTest.qWait(40)
    assert not window.timer.isActive()
    assert window.grab().toImage().pixelColor(100,100).name() == COLORS[0]
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert window.index == len(COLORS)-1
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert window.index == 0
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.timer.isActive()
    QTest.qWait(300)
    assert window.index == 1
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert not window.timer.isActive()
    QTest.keyClick(window, Qt.Key.Key_Escape)

def test_gray_screens(qt):
    window = Transitions(dict(DEFAULTS, motion="Gray-to-Gray Patterns", hold=.25))
    window.launch(qt.primaryScreen())
    QTest.qWait(40)
    assert not window.timer.isActive()
    for index in range(len(GRAY_PATTERNS)):
        assert window.index == index
        assert not window.grab().isNull()
        if index < len(GRAY_PATTERNS)-1:
            QTest.keyClick(window, Qt.Key.Key_Right)
    assert not window.cached_rings.isNull()
    assert window.gray_timer.isActive()
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.timer.isActive() and not window.gray_timer.isActive()
    QTest.qWait(300)
    assert window.index == 0
    QTest.keyClick(window, Qt.Key.Key_Escape)

def test_dimming_reseeds_on_space(qt):
    window = Motion(dict(DEFAULTS, motion="Local Dimming"))
    window.launch(qt.primaryScreen())
    for _ in range(4):
        old = window.dimming
        QTest.keyClick(window, Qt.Key.Key_Space)
        assert 12 <= len(window.dimming) <= 48
        assert len(window.dimming) != len(old)
        assert len({(x,y) for x,y,_,_ in window.dimming}) == len(window.dimming)
    QTest.keyClick(window, Qt.Key.Key_Escape)

def test_square_modes_live_software_timing(qt):
    assert LANE_RATIOS == (2.0, 1.5, 1.0, .5)
    assert set(FOUR_LANES) == {"Pepper", "Cart", "Airplane", *SQUARE_MODES}
    for mode in SQUARE_MODES:
        window = Motion(dict(DEFAULTS, motion=mode, fps=60))
        window.launch(qt.primaryScreen())
        for _ in range(40):
            QTest.qWait(40)
            if window.live_stats.get("request_samples", 0) > 2:
                break
        assert window.live_stats["fps"] > 0
        assert window.live_stats["mean_ms"] > 0
        assert window.live_stats["request_to_paint_ms"] >= 0
        QTest.keyClick(window, Qt.Key.Key_Escape)
