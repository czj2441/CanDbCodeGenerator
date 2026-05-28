"""Signal edit dialog."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from core.can_database import Signal


class SignalDialog(QDialog):
    """Dialog for creating or editing a CAN signal."""

    BYTE_ORDERS = ["little_endian", "big_endian"]
    BYTE_ORDER_LABELS = ["Intel (Little Endian)", "Motorola (Big Endian)"]

    MUX_MODES = ["none", "multiplexer", "multiplexed"]
    MUX_MODE_LABELS = ["None", "Multiplexer", "Multiplexed"]

    def __init__(self, signal: Signal | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self._signal = signal
        self.setWindowTitle("Edit Signal" if signal else "Add Signal")
        self.setMinimumWidth(460)
        self._setup_ui()
        if signal:
            self._populate(signal)

    # -- UI ----------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the form layout."""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. EngineSpeed")
        form.addRow("Name:", self._name_edit)

        # Start Bit
        self._start_bit_spin = QSpinBox()
        self._start_bit_spin.setRange(0, 63)
        form.addRow("Start Bit:", self._start_bit_spin)

        # Length
        self._length_spin = QSpinBox()
        self._length_spin.setRange(1, 64)
        self._length_spin.setValue(8)
        form.addRow("Length:", self._length_spin)

        # Byte Order
        self._byte_order_combo = QComboBox()
        self._byte_order_combo.addItems(self.BYTE_ORDER_LABELS)
        form.addRow("Byte Order:", self._byte_order_combo)

        # Signed
        self._signed_check = QCheckBox()
        form.addRow("Signed:", self._signed_check)

        # Factor
        self._factor_spin = QDoubleSpinBox()
        self._factor_spin.setRange(-1e9, 1e9)
        self._factor_spin.setDecimals(6)
        self._factor_spin.setValue(1.0)
        form.addRow("Factor:", self._factor_spin)

        # Offset
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-1e9, 1e9)
        self._offset_spin.setDecimals(6)
        form.addRow("Offset:", self._offset_spin)

        # Min Value
        self._min_spin = QDoubleSpinBox()
        self._min_spin.setRange(-1e9, 1e9)
        self._min_spin.setDecimals(6)
        form.addRow("Min Value:", self._min_spin)

        # Max Value
        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(-1e9, 1e9)
        self._max_spin.setDecimals(6)
        form.addRow("Max Value:", self._max_spin)

        # Unit
        self._unit_edit = QLineEdit()
        self._unit_edit.setPlaceholderText("e.g. rpm, V, °C")
        form.addRow("Unit:", self._unit_edit)

        # Comment
        self._comment_edit = QTextEdit()
        self._comment_edit.setMaximumHeight(60)
        self._comment_edit.setPlaceholderText("Optional comment …")
        form.addRow("Comment:", self._comment_edit)

        # Multiplexer Mode
        self._mux_combo = QComboBox()
        self._mux_combo.addItems(self.MUX_MODE_LABELS)
        form.addRow("MUX Mode:", self._mux_combo)

        # Multiplexer Value (only relevant when mode == "multiplexed")
        self._mux_value_spin = QSpinBox()
        self._mux_value_spin.setRange(0, 65535)
        self._mux_value_spin.setEnabled(False)
        form.addRow("MUX Value:", self._mux_value_spin)

        # Enable mux_value_spin only when "multiplexed" is selected
        self._mux_combo.currentIndexChanged.connect(self._on_mux_mode_changed)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton("OK")
        self._cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self.reject)

    def _on_mux_mode_changed(self, idx: int) -> None:
        """Enable mux_value_spin only when multiplexed mode is selected."""
        self._mux_value_spin.setEnabled(self.MUX_MODES[idx] == "multiplexed")

    def _populate(self, sig: Signal) -> None:
        """Fill the form from an existing signal."""
        self._name_edit.setText(sig.name)
        self._start_bit_spin.setValue(sig.start_bit)
        self._length_spin.setValue(sig.length)

        if sig.byte_order == "big_endian":
            self._byte_order_combo.setCurrentIndex(1)
        else:
            self._byte_order_combo.setCurrentIndex(0)

        self._signed_check.setChecked(sig.is_signed)
        self._factor_spin.setValue(sig.factor)
        self._offset_spin.setValue(sig.offset)
        self._min_spin.setValue(sig.min_val)
        self._max_spin.setValue(sig.max_val)
        self._unit_edit.setText(sig.unit)
        self._comment_edit.setPlainText(sig.comment)

        if sig.multiplexer_mode in self.MUX_MODES:
            self._mux_combo.setCurrentIndex(self.MUX_MODES.index(sig.multiplexer_mode))
        self._mux_value_spin.setValue(sig.multiplexer_value)

    def _on_ok(self) -> None:
        """Validate and accept."""
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            return
        self.accept()

    # -- Public API -------------------------------------------------------

    def get_signal(self) -> Signal:
        """Return the signal built from the dialog data."""
        byte_order = self.BYTE_ORDERS[self._byte_order_combo.currentIndex()]
        mux_mode = self.MUX_MODES[self._mux_combo.currentIndex()]

        if self._signal:
            self._signal.name = self._name_edit.text().strip()
            self._signal.start_bit = self._start_bit_spin.value()
            self._signal.length = self._length_spin.value()
            self._signal.byte_order = byte_order
            self._signal.is_signed = self._signed_check.isChecked()
            self._signal.factor = self._factor_spin.value()
            self._signal.offset = self._offset_spin.value()
            self._signal.min_val = self._min_spin.value()
            self._signal.max_val = self._max_spin.value()
            self._signal.unit = self._unit_edit.text().strip()
            self._signal.comment = self._comment_edit.toPlainText().strip()
            self._signal.multiplexer_mode = mux_mode
            self._signal.multiplexer_value = self._mux_value_spin.value()
            return self._signal
        else:
            return Signal(
                name=self._name_edit.text().strip(),
                start_bit=self._start_bit_spin.value(),
                length=self._length_spin.value(),
                byte_order=byte_order,
                is_signed=self._signed_check.isChecked(),
                factor=self._factor_spin.value(),
                offset=self._offset_spin.value(),
                min_val=self._min_spin.value(),
                max_val=self._max_spin.value(),
                unit=self._unit_edit.text().strip(),
                comment=self._comment_edit.toPlainText().strip(),
                multiplexer_mode=mux_mode,
                multiplexer_value=self._mux_value_spin.value(),
            )