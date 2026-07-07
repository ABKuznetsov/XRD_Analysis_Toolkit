from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class _OddWindowMixin:
    def _odd(self, value: int) -> int:
        value = max(3, int(value))
        return value if value % 2 else value + 1


class _SliderRow(QWidget):
    released = Signal()

    def __init__(self, minimum: int, maximum: int, value: int, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        self._suffix = suffix
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(max(1, (maximum - minimum) // 8))
        self.value_label = QLabel()
        self.value_label.setMinimumWidth(52)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(self._update_label)
        self.slider.sliderReleased.connect(self.released)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self._update_label(value)

    def value(self) -> int:
        return int(self.slider.value())

    def set_value(self, value: int) -> None:
        self.slider.setValue(int(value))

    def _update_label(self, value: int) -> None:
        self.value_label.setText(f"{int(value)}{self._suffix}")


class SmoothPanel(QWidget, _OddWindowMixin):
    previewRequested = Signal()
    applyRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, default_window: int, parent=None) -> None:
        super().__init__(parent)
        self._default_window = min(self._odd(default_window), 21)
        self.setObjectName("preprocessingPanel")
        self.setMinimumWidth(460)

        self._method = QComboBox()
        self._method.addItem("Savitzky-Golay", "savgol")
        self._method.addItem("Moving average", "moving")
        self._method.addItem("Gaussian", "gaussian")
        self._window = _SliderRow(3, 41, self._default_window)
        self._window.slider.setSingleStep(2)
        self._window.slider.setPageStep(4)
        self._polyorder = QComboBox()
        self._polyorder.addItem("2", 2)
        self._polyorder.addItem("3", 3)
        self._strength = _SliderRow(1, 10, 2)
        self._strength.setToolTip("Gaussian sigma x 10; only used by Gaussian smoothing.")
        self._passes = QComboBox()
        self._passes.addItem("1", 1)
        self._passes.addItem("2", 2)

        self._method.currentIndexChanged.connect(self._method_changed)
        self._window.released.connect(self.previewRequested)
        self._strength.released.connect(self.previewRequested)
        self._passes.currentIndexChanged.connect(self.previewRequested)
        self._polyorder.currentIndexChanged.connect(self.previewRequested)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Function", self._method)
        form.addRow("Window", self._window)
        form.addRow("Polynomial order", self._polyorder)
        form.addRow("Strength", self._strength)
        form.addRow("Passes", self._passes)

        auto_button = QPushButton("Auto")
        cancel_button = QPushButton("Cancel")
        ok_button = QPushButton("OK")
        auto_button.clicked.connect(self.apply_auto)
        cancel_button.clicked.connect(self.cancelRequested)
        ok_button.clicked.connect(self.applyRequested)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(auto_button)
        button_row.addWidget(cancel_button)
        button_row.addWidget(ok_button)

        hint = QLabel("Preview updates when you release a slider. Use small windows to preserve sharp XRD peaks.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4af;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Smooth the active XRD pattern."))
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        self._method_changed()

    def _method_changed(self) -> None:
        method = self.method()
        self._polyorder.setEnabled(method == "savgol")
        self._strength.setEnabled(method == "gaussian")
        self.previewRequested.emit()

    def apply_auto(self) -> None:
        self._method.setCurrentIndex(0)
        self._window.set_value(self._default_window)
        self._polyorder.setCurrentIndex(0)
        self._strength.set_value(2)
        self._passes.setCurrentIndex(0)
        self.previewRequested.emit()

    def method(self) -> str:
        return str(self._method.currentData())

    def window_size(self) -> int:
        return self._odd(self._window.value())

    def polyorder(self) -> int:
        return int(self._polyorder.currentData())

    def gaussian_sigma(self) -> float:
        return max(0.1, self._strength.value() / 10.0)

    def passes(self) -> int:
        return max(1, int(self._passes.currentData()))


class BackgroundRemovalPanel(QWidget):
    previewRequested = Signal()
    applyRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, default_degree: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._default_degree = int(default_degree)
        self.setObjectName("preprocessingPanel")
        self.setMinimumWidth(460)

        self._method = QComboBox()
        self._method.addItem("Auto envelope", "auto")
        self._method.addItem("Polynomial", "polynomial")
        self._method.addItem("Constant floor", "constant")
        self._degree = _SliderRow(2, 30, self._default_degree)
        self._degree.slider.setPageStep(2)
        self._floor = _SliderRow(1, 40, 15, "%")

        self._method.currentIndexChanged.connect(self._method_changed)
        self._degree.released.connect(self.previewRequested)
        self._floor.released.connect(self.previewRequested)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Function", self._method)
        form.addRow("Polynomial degree", self._degree)
        form.addRow("Floor percentile", self._floor)

        auto_button = QPushButton("Auto")
        cancel_button = QPushButton("Cancel")
        ok_button = QPushButton("OK")
        auto_button.clicked.connect(self.apply_auto)
        cancel_button.clicked.connect(self.cancelRequested)
        ok_button.clicked.connect(self.applyRequested)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(auto_button)
        button_row.addWidget(cancel_button)
        button_row.addWidget(ok_button)

        hint = QLabel("Polynomial fitting can help when the envelope removes too much broad-peak intensity; constant floor is conservative.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4af;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Subtract the background from the active pattern."))
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        self._method_changed()

    def _method_changed(self) -> None:
        method = self.method()
        self._degree.setEnabled(method == "polynomial")
        self._floor.setEnabled(method == "constant")
        self.previewRequested.emit()

    def apply_auto(self) -> None:
        self._method.setCurrentIndex(0)
        self._degree.set_value(self._default_degree)
        self._floor.set_value(15)
        self.previewRequested.emit()

    def method(self) -> str:
        return str(self._method.currentData())

    def degree(self) -> int:
        return int(self._degree.value())

    def floor_percentile(self) -> int:
        return int(self._floor.value())


class SmoothDialog(QDialog):
    def __init__(self, default_window: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smooth XRD pattern")
        self._panel = SmoothPanel(default_window, self)
        self._panel.applyRequested.connect(self.accept)
        self._panel.cancelRequested.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._panel)

    def auto_enabled(self) -> bool:
        return False

    def method(self) -> str:
        return self._panel.method()

    def window_size(self) -> int:
        return self._panel.window_size()

    def polyorder(self) -> int:
        return self._panel.polyorder()

    def gaussian_sigma(self) -> float:
        return self._panel.gaussian_sigma()

    def passes(self) -> int:
        return self._panel.passes()


class BackgroundRemovalDialog(QDialog):
    def __init__(self, default_degree: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove background")
        self._panel = BackgroundRemovalPanel(default_degree, self)
        self._panel.applyRequested.connect(self.accept)
        self._panel.cancelRequested.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._panel)

    def auto_enabled(self) -> bool:
        return self._panel.method() == "auto"

    def method(self) -> str:
        return self._panel.method()

    def degree(self) -> int:
        return self._panel.degree()
