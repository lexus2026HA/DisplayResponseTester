import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.display_info.model import GRAY_LEVELS, PANELS, parse_edid, resolve_screen, rows, text_value
from app.display_info.windows import read_windows
from app.gui.common import button, combo, form, horizontal, page, scrollable, spin, start_task
from app.gui.hardware import HardwarePage
from app.reports.export import export, report_data, write_json
from app.slideshow.view import Slideshow, scan
from app.software_tests.latency import SoftwareLatency
from app.software_tests.motion import FOUR_LANES, MODES, Motion
from app.software_tests.patterns import TRANSITION_MODES, Transitions
from app.utils.settings import ROOT

COPYABLE_DISPLAY_VALUES = {"Модель", "Имя устройства из EDID", "Спецификация модели"}

STYLES = {
    "Dark": ("#131923","#1d2838","#e8eff9","#a8b7cc","#344660","#78e6c6","#111b26"),
    "Light": ("#f1f5fa","#ffffff","#1c2e45","#4f6279","#bac9da","#08775f","#ffffff"),
}

def appearance(theme):
    bg, surface, fg, muted, border, accent, dark_on_accent = STYLES.get(theme, STYLES["Dark"])
    QApplication.instance().setStyleSheet(f"""
    QWidget {{ background:{bg}; color:{fg}; font-family:'Segoe UI'; font-size:10pt; }}
    QLabel#heading {{ font-size:19pt; font-weight:650; }}
    QLabel#muted {{ color:{muted}; }}
    QTabWidget::pane {{ border:1px solid {border}; }}
    QTabBar::tab {{ padding:9px 15px; color:{muted}; border-bottom:2px solid transparent; }}
    QTabBar::tab:selected {{ color:{fg}; border-bottom:2px solid {accent}; }}
    QPushButton,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{ border:1px solid {border};
        border-radius:5px; padding:5px 8px; background:{surface}; }}
    QPushButton:hover,QLineEdit:focus,QComboBox:focus {{ border-color:{accent}; }}
    QPushButton[primary="true"] {{ background:{accent}; color:{dark_on_accent}; font-weight:650; }}
    QPushButton:disabled {{ background:{surface}; color:{muted}; }}
    QTableWidget,QPlainTextEdit {{ background:{surface}; border:1px solid {border};
        gridline-color:{border}; alternate-background-color:{bg};
        selection-background-color:{border}; selection-color:{fg}; }}
    QComboBox QAbstractItemView {{ background:{surface}; color:{fg}; selection-background-color:{border}; }}
    QHeaderView::section {{ background:{surface}; color:{fg}; padding:6px; border:0; }}
    """)

class MainWindow(QMainWindow):
    def __init__(self, settings, read_display=read_windows):
        super().__init__()
        self.settings = settings
        self.read_display = read_display
        self.records = {}
        self.display_data = {}
        self.motion_results = {}
        self.hardware_results = {}
        self.active = None
        self.slide = None
        self.images = ROOT / "Images"
        self.images.mkdir(exist_ok=True)
        self.files = []
        self.refreshing = False
        self.setWindowTitle("Display Response Tester V1.2")
        self.resize(1100, 750)
        base = QWidget()
        self.setCentralWidget(base)
        root = QVBoxLayout(base)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        self.display_combo = QComboBox()
        self.display_combo.setMinimumContentsLength(25)
        self.display_combo.currentIndexChanged.connect(self.display_selected)
        self.refresh_button = button("Обновить информацию", self.refresh)
        horizontal(root, QLabel("Дисплей"), self.display_combo, self.refresh_button)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.make_info()
        self.make_slideshow()
        self.make_motion()
        self.hardware = HardwarePage(settings, self.selected_screen, self.display_combo.currentData, self.launch, self.store_hardware,
                                     lambda: self.export_dialog())
        self.tabs.addTab(scrollable(self.hardware.widget), "Hardware Test")
        self.make_reports()
        self.make_settings()
        self.apply_theme()
        self.rescan()
        self.refresh()
        QApplication.instance().screenAdded.connect(self.refresh)
        QApplication.instance().screenRemoved.connect(self.refresh)

    def make_info(self):
        w, layout = page("Характеристики дисплея",
                         "Текущий видеосигнал, EDID и возможности. Источник указан для каждого параметра.")
        self.info = QTableWidget(0, 3)
        self.info.cellClicked.connect(self.copy_display_value)
        self.info.setHorizontalHeaderLabels(["Параметр", "Значение", "Источник"])
        header = self.info.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.info.setWordWrap(True)
        self.info.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.info.setAlternatingRowColors(True)
        layout.addWidget(self.info, 1)
        self.panel = combo(PANELS, PANELS[0])
        self.backlight = combo(("Неизвестно", "Edge LED", "Direct LED", "FALD", "MiniLED", "MiniLED FALD", "Другая"), "Неизвестно")
        self.panel.activated.connect(self.override_panel)
        self.backlight.activated.connect(self.override_panel)
        horizontal(layout, QLabel("Ручной выбор матрицы"), self.panel, QLabel("Подсветка"), self.backlight,
                   button("Экспорт TXT / HTML", lambda: self.export_dialog(display_only=True)))
        self.tabs.addTab(w, "Display Info")

    def copy_display_value(self, row, column):
        name = self.info.item(row, 0)
        value = self.info.item(row, 1)
        if name is None or value is None or name.text() not in COPYABLE_DISPLAY_VALUES:
            return
        QApplication.clipboard().setText(value.text())
        self.statusBar().showMessage(f"Скопировано: {name.text()}", 3500)

    def refresh(self, *_):
        if self.refreshing:
            return
        self.refreshing = True
        self.refresh_button.setEnabled(False)
        self.statusBar().showMessage("Чтение Windows API и EDID…")
        start_task(self.read_display, self.refresh_finished,
                   lambda error: self.refresh_finished([], error))

    def refresh_finished(self, records, error=""):
        options = {}
        for record in records:
            options[record["id"]] = record
        screens = QApplication.screens()
        mapped = [self.screen_for(screens, item) for item in records]
        for screen in screens:
            if screen not in mapped:
                origin = [screen.geometry().x(), screen.geometry().y()]
                identity = f"qt:{screen.name()}:{origin}"
                options[identity] = {"id": identity, "screen": screen.name(), "name": screen.model(),
                                     "origin": origin, "source": "Qt QScreen",
                                     "hz": screen.refreshRate() if screen.refreshRate() > 1 else None}
        self.records = options
        self.display_combo.blockSignals(True)
        self.display_combo.clear()
        for identity, item in options.items():
            friendly = item.get("name") or item["screen"]
            self.display_combo.addItem(f"{friendly} · {item['screen']}", identity)
        index = self.display_combo.findData(self.settings["display"])
        if index < 0:
            primary = QApplication.primaryScreen()
            index = next((i for i, rec in enumerate(options.values()) if primary and
                          self.screen_for(screens, rec) == primary), 0)
        self.display_combo.setCurrentIndex(index)
        self.display_combo.blockSignals(False)
        self.refresh_button.setEnabled(True)
        self.refreshing = False
        self.display_selected()
        self.statusBar().showMessage(error or f"Активных видеовыходов: {len(options)}", 5000)

    def display_selected(self, *_):
        identity = self.display_combo.currentData()
        if identity:
            self.settings["display"] = identity
            self.settings.save()
        override = self.settings["overrides"].get(identity, {})
        self.panel.setCurrentText(override.get("panel", "Неизвестно"))
        self.backlight.setCurrentText(override.get("backlight", "Неизвестно"))
        self.update_info()

    def update_info(self):
        identity = self.display_combo.currentData()
        self.display_data = rows(self.records.get(identity, {}), self.settings["overrides"].get(identity))
        for run in reversed(self.motion_results.get(identity, [])):
            stats = run["statistics"]
            if "fps" in stats:
                self.display_data["Программная оценка движения"] = {
                    "value": f"{run['mode']} • {stats['fps']} FPS • {stats['mean_ms']} мс между отрисовками",
                    "source": "Измерение приложения",
                }
                break
        for run in reversed(self.motion_results.get(identity, [])):
            if run["mode"] == "Software Latency" and run["statistics"]:
                self.display_data["Software Latency: интервал кадра, мс"] = {
                    "value": run["statistics"]["mean_ms"], "source": "Измерение приложения",
                }
                break
        self.info.setRowCount(len(self.display_data))
        for i,(label, pair) in enumerate(self.display_data.items()):
            for j,value in enumerate((label,text_value(pair["value"]),pair["source"])):
                item = QTableWidgetItem(value)
                tip = value
                if label in COPYABLE_DISPLAY_VALUES:
                    tip += "\nЩёлкните, чтобы скопировать значение."
                item.setToolTip(tip)
                self.info.setItem(i,j,item)
        self.info.resizeRowsToContents()

    def override_panel(self, *_):
        identity = self.display_combo.currentData()
        if not identity:
            return
        self.settings["overrides"][identity] = {k: w.currentText() for k,w in
                                                (("panel",self.panel),("backlight",self.backlight))
                                                if w.currentText() != "Неизвестно"}
        self.settings.save()
        self.update_info()

    @staticmethod
    def screen_for(screens, record):
        return resolve_screen(screens, record["screen"], record.get("origin"), record.get("name"))

    def selected_screen(self):
        record = self.records.get(self.display_combo.currentData())
        screen = self.screen_for(QApplication.screens(), record) if record else None
        if screen is None:
            self.statusBar().showMessage("Выберите доступный дисплей и обновите информацию.", 8000)
        return screen

    def launch(self, window, screen, fullscreen=True):
        if self.active is not None:
            self.active.close()
        self.active = window
        window.destroyed.connect(lambda *_: self.clear_active(window))
        window.launch(screen, fullscreen)

    def clear_active(self, window):
        if self.active is window:
            self.active = None

    def make_slideshow(self):
        w, layout = page("Слайдшоу", "Изображения JPG и PNG из папки Images. Esc возвращает к управлению.")
        self.slide_status = QLabel()
        layout.addWidget(self.slide_status)
        f = form(layout)
        self.fit = combo(("Fit", "Fill"), self.settings["fit"])
        self.fit.currentTextChanged.connect(lambda value: self.slide_setting("fit",value))
        self.overlay = QCheckBox("Показывать имя файла, номер и интервал")
        self.overlay.setChecked(self.settings["overlay"])
        self.overlay.toggled.connect(lambda value: self.slide_setting("overlay",value))
        f.addRow("Масштабирование", self.fit)
        f.addRow("Оверлей", self.overlay)
        self.slide_btn = button("Запуск на полный экран", self.open_slide, True)
        horizontal(layout, self.slide_btn, button("Открыть Images", lambda: self.open_folder(self.images)),
                   button("Пересканировать", self.rescan))
        self.slide_play = button("Пауза / Продолжить", lambda: self.slide.toggle() if self.slide else None)
        self.slide_prev = button("Предыдущее", lambda: self.slide.step(-1) if self.slide else None)
        self.slide_next = button("Следующее", lambda: self.slide.step(1) if self.slide else None)
        self.interval_label = QLabel(f"{self.settings['interval']} с")
        horizontal(layout, self.slide_play,self.slide_prev,self.slide_next,button("−",lambda: self.adjust_slide(-1)),
                   self.interval_label,button("+",lambda: self.adjust_slide(1)))
        layout.addWidget(QLabel("← / →  Кадры     •     ↑ / ↓ или + / −  Интервал     •     Space  Пауза"))
        layout.addStretch()
        self.tabs.addTab(w,"Slideshow")
        self.slide_buttons(False)

    def slide_buttons(self, enabled):
        for control in (self.slide_play,self.slide_prev,self.slide_next):
            control.setEnabled(enabled)

    def rescan(self):
        try:
            self.files = scan(self.images)
            n = len(self.files)
            self.slide_status.setText(f"Изображений: {n}" if n else
                                      "Папка Images пуста. Откройте папку и добавьте JPG или PNG.")
        except OSError as error:
            self.files = []
            self.slide_status.setText(str(error))
        self.slide_btn.setEnabled(bool(self.files))

    def slide_setting(self,key,value):
        self.settings[key] = value
        if self.slide:
            setattr(self.slide,key,value)
            self.slide.update()
        self.settings.save()

    def open_slide(self):
        self.rescan()
        screen = self.selected_screen()
        if screen is None or not self.files:
            return
        window = Slideshow(self.files,self.settings["interval"],self.settings["fit"],self.settings["overlay"])
        window.changed.connect(self.slide_changed)
        window.destroyed.connect(lambda *_: self.slide_closed(window))
        self.slide = window
        self.slide_changed(window.interval, window.playing, window.index)
        self.slide_buttons(True)
        self.launch(window,screen)

    def slide_closed(self, window):
        if self.slide is window:
            self.slide = None
            self.slide_buttons(False)

    def slide_changed(self, interval, playing, index):
        self.interval_label.setText(f"{interval} с")
        self.slide_play.setText("Пауза" if playing else "Продолжить")
        if self.settings["interval"] != interval:
            self.settings["interval"] = interval
            self.settings.save()
        self.slide_status.setText(f"{index+1}/{len(self.slide.files)} • {self.slide.files[index].name}")

    def adjust_slide(self, delta):
        if self.slide:
            self.slide.adjust(delta)
        else:
            interval = max(1,min(5,self.settings["interval"]+delta))
            self.settings["interval"] = interval
            self.interval_label.setText(f"{interval} с")
            self.settings.save()

    def make_motion(self):
        w, layout = page("Движение и программная задержка",
                         "Скорость задаётся в физических пикселях в секунду. FPS генератора измеряется по отрисовкам.")
        f = form(layout)
        self.motion_options = {}
        specs = [
            ("Тест","motion",combo((*MODES,*TRANSITION_MODES,"Software Latency"),self.settings["motion"])),
            ("Скорость","speed",spin(10,12000,self.settings["speed"]," px/s")),
            ("Целевой FPS генератора","fps",spin(1,500,self.settings["fps"])),
            ("Объекты в строке","count",spin(1,12,self.settings["count"])),
            ("Строки в остальных режимах","lanes",spin(1,6,self.settings["lanes"])),
            ("Размер объекта","size",spin(24,450,self.settings["size"]," px")),
            ("Направление","direction",combo(("→","←"),self.settings["direction"])),
            ("Колёса / пропеллер (0 — авто для Cart)","rpm",spin(0,6000,self.settings["rpm"]," rpm")),
            ("Переход из","gray_from",combo(GRAY_LEVELS,self.settings["gray_from"])),
            ("Переход в","gray_to",combo(GRAY_LEVELS,self.settings["gray_to"])),
            ("Длительность уровня","hold",spin(.25,10,self.settings["hold"]," с",True)),
        ]
        for label,key,control in specs:
            f.addRow(label,control)
            self.motion_options[key] = control
        self.motion_hint = QLabel()
        self.motion_hint.setWordWrap(True)
        layout.addWidget(self.motion_hint)
        self.motion_options["motion"].currentTextChanged.connect(self.motion_help)
        self.motion_help(self.motion_options["motion"].currentText())
        self.color_button = button(self.settings["background"], self.choose_color)
        f.addRow("Фон", self.color_button)
        self.fullscreen = QCheckBox("Полноэкранный режим")
        self.fullscreen.setChecked(self.settings.get("motion_fullscreen",True))
        self.motion_status = QLabel("VSync · управляется Windows/Qt")
        self.motion_status.setWordWrap(True)
        horizontal(layout,button("Запустить тест", self.open_motion, True), self.fullscreen)
        layout.addWidget(self.motion_status)
        layout.addStretch()
        self.tabs.addTab(scrollable(w),"Motion Test")

    def motion_help(self, mode):
        self.motion_options["lanes"].setEnabled(mode == "Moving Text")
        if mode in FOUR_LANES:
            note = "Сверху вниз: 200%, 150%, 100%, 50%. В тестах с квадратами FPS и интервалы видны сразу."
        elif mode in TRANSITION_MODES:
            note = "Space — авто / пауза, стрелки — выбор кадра, H — показать подсказку."
        elif mode == "Local Dimming":
            note = "Space — новое число и размещение тёмных квадратов."
        elif mode == "Software Latency":
            note = "Один движущийся квадрат. ← / → меняют цвет, ↑ / ↓ меняют скорость. FPS и время кадра видны слева вверху."
        else:
            note = ""
        self.motion_hint.setText(note)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.settings["background"]), self, "Цвет фона")
        if color.isValid():
            self.settings["background"] = color.name()
            self.color_button.setText(color.name())
            self.settings.save()

    def save_motion_settings(self):
        for key, control in self.motion_options.items():
            value = control.currentText() if isinstance(control,QComboBox) else control.value()
            self.settings[key] = int(value) if key in ("gray_from","gray_to") else value
        self.settings["motion_fullscreen"] = self.fullscreen.isChecked()
        self.settings.save()

    def open_motion(self):
        screen = self.selected_screen()
        if screen is None:
            return
        self.save_motion_settings()
        keys = (*self.motion_options,"background","motion_fullscreen")
        opts = {key:self.settings[key] for key in keys}
        identity = self.display_combo.currentData()
        mode = opts["motion"]
        if mode in TRANSITION_MODES:
            self.motion_status.setText("Space — авто / пауза • стрелки — выбор • Esc — выход")
            self.launch(Transitions(opts), screen, self.fullscreen.isChecked())
            return
        window = SoftwareLatency(opts) if mode == "Software Latency" else Motion(opts)
        latest = {}

        def show_stats(stats):
            latest.clear()
            latest.update(stats)
            if not stats:
                return
            if "fps" in stats:
                text = (f"{stats['fps']:.2f} FPS   •   кадр {stats['mean_ms']:.3f} мс   •   σ {stats['jitter_ms']:.3f} мс"
                        f"   •   P95 {stats['p95_ms']:.3f} мс")
                if "request_to_paint_ms" in stats:
                    text += f"   •   Запрос → Qt: {stats['request_to_paint_ms']:.3f} мс"
            else:
                text = "Ожидание интервалов отрисовки…"
            self.motion_status.setText(text)

        def finished(*_):
            if latest:
                result = {"mode":mode,"settings":opts,"statistics":latest.copy(),"source":"Программное измерение"}
                self.motion_results.setdefault(identity, []).append(result)
                if self.display_combo.currentData() == identity:
                    self.update_info()

        self.motion_status.setText("Идёт измерение кадров…")
        window.stats_ready.connect(show_stats)
        window.destroyed.connect(finished)
        self.launch(window,screen,self.fullscreen.isChecked())

    def make_reports(self):
        w, layout = page("Отчёты", "Сохраните характеристики выбранного дисплея, условия и результаты текущего сеанса.")
        self.conditions = QPlainTextEdit()
        self.conditions.setPlaceholderText("Условия тестирования, настройки монитора и визуальные наблюдения")
        layout.addWidget(self.conditions,1)
        horizontal(layout,button("Сохранить отчёт",self.export_dialog,True),
                   button("Открыть папку отчётов", lambda: self.open_folder(self.report_dir())))
        self.report_status = QLabel()
        self.report_status.setWordWrap(True)
        layout.addWidget(self.report_status)
        layout.addStretch()
        self.tabs.addTab(w,"Reports")

    def make_settings(self):
        w, layout = page("Настройки", "Выбор дисплея, слайдшоу, движение, камера и тема сохраняются в config/settings.json.")
        f = form(layout)
        self.theme = combo(STYLES,self.settings["theme"])
        self.theme.currentTextChanged.connect(self.apply_theme)
        self.path_field = QLineEdit(str(self.report_dir()))
        self.path_field.editingFinished.connect(self.store_report_path)
        f.addRow("Тема",self.theme)
        f.addRow("Папка отчётов",self.path_field)
        horizontal(layout, button("Выбрать папку",self.pick_report_folder))
        layout.addStretch()
        self.tabs.addTab(w,"Settings")

    def report_dir(self):
        return Path(self.settings["report_path"]) if self.settings["report_path"] else ROOT / "results"

    def apply_theme(self, value=None):
        if value:
            self.settings["theme"] = value
            self.settings.save()
        appearance(self.settings["theme"])

    def store_report_path(self):
        path = self.path_field.text().strip()
        self.settings["report_path"] = str(Path(path).resolve()) if path else ""
        self.settings.save()

    def pick_report_folder(self):
        path = QFileDialog.getExistingDirectory(self,"Папка отчётов",str(self.report_dir()))
        if path:
            self.path_field.setText(path)
            self.store_report_path()

    def open_folder(self, path):
        try:
            path.mkdir(parents=True,exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise OSError(f"Не удалось открыть папку {path}")
        except OSError as error:
            QMessageBox.warning(self,"Папка",str(error))

    def current_report(self, display_only=False):
        identity = self.display_combo.currentData()
        return report_data(self.display_data,identity,None if display_only else self.hardware_results.get(identity),
                           [] if display_only else self.motion_results.get(identity),self.conditions.toPlainText())

    def store_hardware(self, result):
        identity = result.pop("display_id", self.display_combo.currentData())
        self.hardware_results[identity] = result
        if identity == self.display_combo.currentData():
            report = self.current_report()
        else:
            display = rows(self.records.get(identity, {}), self.settings["overrides"].get(identity))
            report = report_data(display, identity, result, self.motion_results.get(identity),
                                 self.conditions.toPlainText())
        path = self.report_dir() / f"measurement-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}.json"
        start_task(lambda: write_json(path,report),
                   lambda _: self.report_status.setText(f"Измерение сохранено в {path}"),
                   self.report_status.setText)

    def export_dialog(self, _checked=False, display_only=False):
        filters = "HTML (*.html);;PDF (*.pdf);;JSON (*.json);;CSV (*.csv)"
        if display_only:
            filters = "TXT (*.txt);;HTML (*.html)"
        try:
            self.report_dir().mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self,"Экспорт",str(error))
            return
        raw, selected = QFileDialog.getSaveFileName(self,"Сохранить отчёт",
                                      str(self.report_dir()/f"display-{datetime.now():%Y%m%d-%H%M%S}"),filters)
        if not raw:
            return
        path = Path(raw)
        if not path.suffix:
            path = path.with_suffix(selected.split("*")[-1].rstrip(")"))
        report = self.current_report(display_only)
        def exported(_):
            message = f"Отчёт сохранён в {path}"
            self.report_status.setText(message)
            self.statusBar().showMessage(message, 6000)

        start_task(lambda: export(path, report, display_only=display_only),
                   exported,
                   lambda error: QMessageBox.warning(self,"Экспорт",error))

    def closeEvent(self, event):
        if self.hardware.options is not None:
            self.hardware.stop()
            self.statusBar().showMessage("Завершается запись. Закройте окно после завершения.", 5000)
            event.ignore()
            return
        if self.active:
            self.active.close()
        self.save_motion_settings()
        self.hardware.persist()
        self.store_report_path()
        super().closeEvent(event)
