"""Message edit dialog."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from core.can_database import Message
from gui.widgets import HexSpinBox


class MessageDialog(QDialog):
    """Dialog for creating or editing a CAN message."""

    def __init__(self, message: Message | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self._message = message
        self.setWindowTitle("Edit Message" if message else "Add Message")
        self.setMinimumWidth(420)
        self._setup_ui()
        if message:
            self._populate(message)

    # -- UI ----------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the form layout."""
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. EngineStatus")
        form.addRow("Name:", self._name_edit)

        # ID (hex)
        self._id_spin = HexSpinBox()
        form.addRow("ID:", self._id_spin)

        # DLC
        self._dlc_spin = QSpinBox()
        self._dlc_spin.setRange(0, 8)
        self._dlc_spin.setValue(8)
        form.addRow("DLC:", self._dlc_spin)

        # Cycle Time
        self._cycle_spin = QSpinBox()
        self._cycle_spin.setRange(0, 10000)
        self._cycle_spin.setSuffix(" ms")
        self._cycle_spin.setSpecialValueText("Event")
        form.addRow("Cycle Time:", self._cycle_spin)

        # Sender
        self._sender_edit = QLineEdit()
        self._sender_edit.setPlaceholderText("e.g. ECU1")
        form.addRow("Sender:", self._sender_edit)

        # Comment
        self._comment_edit = QTextEdit()
        self._comment_edit.setMaximumHeight(80)
        self._comment_edit.setPlaceholderText("Optional comment …")
        form.addRow("Comment:", self._comment_edit)

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

    def _populate(self, msg: Message) -> None:
        """Fill the form from an existing message."""
        self._name_edit.setText(msg.name)
        self._id_spin.setValue(msg.id)
        self._dlc_spin.setValue(msg.dlc)
        self._cycle_spin.setValue(msg.cycle_time)
        self._sender_edit.setText(msg.sender)
        self._comment_edit.setPlainText(msg.comment)

    def _on_ok(self) -> None:
        """Validate and accept."""
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            return
        self.accept()

    # -- Public API -------------------------------------------------------

    def get_message(self) -> Message:
        """Return the message built from the dialog data."""
        if self._message:
            self._message.name = self._name_edit.text().strip()
            self._message.id = self._id_spin.value()
            self._message.dlc = self._dlc_spin.value()
            self._message.cycle_time = self._cycle_spin.value()
            self._message.sender = self._sender_edit.text().strip()
            self._message.comment = self._comment_edit.toPlainText().strip()
            return self._message
        else:
            return Message(
                id=self._id_spin.value(),
                name=self._name_edit.text().strip(),
                dlc=self._dlc_spin.value(),
                cycle_time=self._cycle_spin.value(),
                sender=self._sender_edit.text().strip(),
                comment=self._comment_edit.toPlainText().strip(),
            )