import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget

class Signals(QObject):
    result = Signal(object)
    error = Signal(str)

class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = Signals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self.fn())
        except Exception as error:
            logging.exception("Background task failed")
            self.signals.error.emit(str(error))

def start_task(fn, success, failure):
    task = Task(fn)
    task.signals.result.connect(success, Qt.ConnectionType.QueuedConnection)
    task.signals.error.connect(failure, Qt.ConnectionType.QueuedConnection)
    QThreadPool.globalInstance().start(task)

def button(label, callback, primary=False):
    w = QPushButton(label)
    w.setProperty("primary", primary)
    w.clicked.connect(callback)
    return w

def combo(items, selected):
    w = QComboBox()
    w.addItems([str(item) for item in items])
    index = w.findText(str(selected))
    if index >= 0:
        w.setCurrentIndex(index)
    return w

def spin(low, high, value, suffix="", fractional=False):
    w = QDoubleSpinBox() if fractional else QSpinBox()
    w.setRange(low, high)
    if fractional:
        w.setSingleStep(.1)
    w.setValue(value)
    w.setSuffix(suffix)
    return w

def scrollable(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area

def form(layout):
    w = QWidget()
    f = QFormLayout(w)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    f.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(w)
    return f

def horizontal(layout, *widgets):
    bar = QHBoxLayout()
    for w in widgets:
        bar.addWidget(w)
    bar.addStretch()
    layout.addLayout(bar)
    return bar

def page(title, subtitle):
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(24, 22, 24, 20)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("heading")
    layout.addWidget(heading)
    note = QLabel(subtitle)
    note.setWordWrap(True)
    note.setObjectName("muted")
    layout.addWidget(note)
    return w, layout
