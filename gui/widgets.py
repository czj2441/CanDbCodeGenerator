"""Auxiliary GUI widgets for CanMatrix Editor.

SignalTableModel now works with the per-message signal model:
- Message.signals is a list of Signal objects (not names)
- No global signal registry exists
- All signal operations are scoped to the current message
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QLineEdit, QSpinBox

from cli import CanMatrixSession
from core.can_database import Message, Signal


# ---------------------------------------------------------------------------
# HexSpinBox
# ---------------------------------------------------------------------------

class HexSpinBox(QSpinBox):
    """A spin-box that displays and accepts hexadecimal values."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setRange(0, 0x1FFFFFFF)  # 29-bit extended CAN ID range
        self.setDisplayIntegerBase(16)
        self.setPrefix("0x")

    def textFromValue(self, value: int) -> str:
        """Override to show hex with '0x' prefix."""
        return f"0x{value:X}"

    def valueFromText(self, text: str) -> int:
        """Parse hex text back to int."""
        text = text.strip().upper()
        if text.startswith("0X"):
            text = text[2:]
        elif text.startswith("0x"):
            text = text[2:]
        try:
            return int(text, 16)
        except ValueError:
            return 0


# ---------------------------------------------------------------------------
# SignalTableModel
# ---------------------------------------------------------------------------

_SIGNAL_HEADERS = [
    "Name", "Start Bit", "Length", "Byte Order",
    "Signed", "Factor", "Offset", "Min", "Max",
    "Unit", "Comment",
]


class SignalTableModel(QAbstractTableModel):
    """Table model backing the signal table view for a single message.

    Works with per-message signal model where Message.signals
    is a list of Signal objects (not signal names).
    """

    data_changed = pyqtSignal()

    def __init__(self, session: CanMatrixSession, parent: Any = None) -> None:
        super().__init__(parent)
        self._session = session
        self._message: Message | None = None
        self._headers: list[str] = _SIGNAL_HEADERS

    def set_message(self, message: Message | None) -> None:
        """Bind the model to a new (or None) message."""
        self.beginResetModel()
        self._message = message
        self.endResetModel()

    @property
    def message(self) -> Message | None:
        """Return the currently bound message, if any."""
        return self._message

    def _get_signal(self, row: int) -> Signal | None:
        """Return the Signal object for a row, or None.

        In per-message model, Message.signals is a list of Signal objects.
        """
        if self._message is None or row >= len(self._message.signals):
            return None
        return self._message.signals[row]

    # -- QAbstractTableModel overrides ---------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._message is None:
            return 0
        return len(self._message.signals)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._headers)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or self._message is None:
            return None
        row = index.row()
        col = index.column()
        if row >= len(self._message.signals):
            return None

        sig = self._get_signal(row)
        if sig is None:
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display_value(sig, col)

        if role == Qt.ItemDataRole.EditRole:
            return self._get_edit_value(sig, col)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 2, 5, 6, 7, 8):  # numeric columns
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or self._message is None or role != Qt.ItemDataRole.EditRole:
            return False
        row = index.row()
        col = index.column()
        if row >= len(self._message.signals):
            return False

        # In per-message model, get Signal object directly from message
        sig = self._message.signals[row]
        if sig is None:
            return False

        try:
            self._set_signal_value(sig, col, value)
        except (ValueError, TypeError):
            return False

        self.dataChanged.emit(index, index, [role])
        self.data_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        default = super().flags(index)
        if index.isValid():
            return default | Qt.ItemFlag.ItemIsEditable
        return default

    # -- Helpers -------------------------------------------------------------

    def _signal_attr_map(self) -> dict[int, str]:
        """Column index → Signal attribute name."""
        return {
            0: "name",
            1: "start_bit",
            2: "length",
            3: "byte_order",
            4: "is_signed",
            5: "factor",
            6: "offset",
            7: "min_val",
            8: "max_val",
            9: "unit",
            10: "comment",
        }

    def _get_display_value(self, sig: Signal, col: int) -> str:
        """Return display string for a signal column."""
        attr_map = self._signal_attr_map()
        attr = attr_map.get(col)
        if attr is None:
            return ""
        val = getattr(sig, attr)
        if attr == "is_signed":
            return "Yes" if val else "No"
        if attr == "byte_order":
            return "Intel" if val == "little_endian" else "Motorola"
        return str(val)

    def _get_edit_value(self, sig: Signal, col: int) -> Any:
        """Return raw value for editing."""
        attr_map = self._signal_attr_map()
        attr = attr_map.get(col)
        if attr is None:
            return ""
        return getattr(sig, attr)

    def _set_signal_value(self, sig: Signal, col: int, value: Any) -> None:
        """Set a signal attribute from an edited value.

        In per-message model, this only affects the signal within
        the current message (signals in other messages are independent).
        """
        attr_map = self._signal_attr_map()
        attr = attr_map.get(col)
        if attr is None:
            return

        if attr in ("start_bit", "length"):
            setattr(sig, attr, int(value))
        elif attr in ("factor", "offset", "min_val", "max_val"):
            setattr(sig, attr, float(value))
        elif attr == "is_signed":
            if isinstance(value, bool):
                setattr(sig, attr, value)
            else:
                setattr(sig, attr, str(value).strip().lower() in ("yes", "true", "1"))
        elif attr == "byte_order":
            v = str(value).strip().lower()
            if v in ("intel", "little_endian", "little"):
                setattr(sig, attr, "little_endian")
            elif v in ("motorola", "big_endian", "big"):
                setattr(sig, attr, "big_endian")
        else:
            setattr(sig, attr, str(value))

    def notify_signal_appended(self) -> None:
        """Notify views that a signal was appended (data added via Session)."""
        if self._message is None:
            return
        row = len(self._message.signals) - 1
        if row < 0:
            return
        self.beginInsertRows(QModelIndex(), row, row)
        self.endInsertRows()
        self.data_changed.emit()

    def notify_signal_removed(self, row: int) -> None:
        """Notify views that a signal at *row* was removed (data removed via Session)."""
        if self._message is None or not (0 <= row < len(self._message.signals) + 1):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        self.endRemoveRows()
        self.data_changed.emit()