"""Main window for CanMatrix Editor.

All business logic is delegated to CanMatrixSession so that every
operation has an equivalent headless (CLI) path.  The GUI only handles
PyQt dialogs, tree/table refresh, and status bar updates.
"""

from __future__ import annotations

import os
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cli import CanMatrixSession
from core.can_database import Message, Signal
from gui.message_editor import MessageDialog
from gui.signal_editor import SignalDialog
from gui.widgets import SignalTableModel


class MainWindow(QMainWindow):
    """Top-level application window."""

    _MSG_ID_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self) -> None:
        super().__init__()
        self._session = CanMatrixSession()

        self.setWindowTitle("CanMatrix Editor - Untitled")
        self.resize(1100, 680)

        self._setup_menu()
        self._setup_toolbar()
        self._setup_central()
        self._setup_statusbar()

        self._update_title()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _setup_menu(self) -> None:
        menu_bar = self.menuBar()

        # ---- File ----
        file_menu = menu_bar.addMenu("&File")

        act_new = QAction("&New", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self._on_new)
        file_menu.addAction(act_new)

        file_menu.addSeparator()

        open_menu = file_menu.addMenu("&Open")
        for label, slot in [
            ("Open TOML …", self._on_open_toml),
            ("Open JSON …", self._on_open_json),
            ("Open XML …", self._on_open_xml),
            ("Import DBC …", self._on_import_dbc),
        ]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            open_menu.addAction(action)

        file_menu.addSeparator()

        act_save = QAction("&Save TOML", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._on_save)
        file_menu.addAction(act_save)

        save_as_menu = file_menu.addMenu("Save &As")
        for label, slot in [
            ("Save as JSON …", self._on_save_json),
            ("Save as XML …", self._on_save_xml),
        ]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            save_as_menu.addAction(action)

        file_menu.addSeparator()

        act_export = QAction("&Export DBC …", self)
        act_export.triggered.connect(self._on_export_dbc)
        file_menu.addAction(act_export)

        file_menu.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _setup_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._tb_new = QPushButton("New")
        self._tb_new.clicked.connect(self._on_new)
        toolbar.addWidget(self._tb_new)

        self._tb_open = QPushButton("Open")
        self._tb_open.clicked.connect(self._on_open_toml)
        toolbar.addWidget(self._tb_open)

        self._tb_save = QPushButton("Save")
        self._tb_save.clicked.connect(self._on_save)
        toolbar.addWidget(self._tb_save)

        toolbar.addSeparator()

        self._tb_import = QPushButton("Import DBC")
        self._tb_import.clicked.connect(self._on_import_dbc)
        toolbar.addWidget(self._tb_import)

        self._tb_export = QPushButton("Export DBC")
        self._tb_export.clicked.connect(self._on_export_dbc)
        toolbar.addWidget(self._tb_export)

    # ------------------------------------------------------------------
    # Central widget
    # ------------------------------------------------------------------

    def _setup_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # -- Left panel: message tree --
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)

        left_layout.addWidget(QLabel("<b>Messages</b>"))

        self._msg_tree = QTreeWidget()
        self._msg_tree.setHeaderLabels(["ID", "Name", "DLC"])
        self._msg_tree.setRootIsDecorated(False)
        self._msg_tree.setAlternatingRowColors(True)
        self._msg_tree.setSelectionMode(
            self._msg_tree.selectionMode().SingleSelection
        )
        self._msg_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._msg_tree.customContextMenuRequested.connect(self._on_msg_context_menu)
        self._msg_tree.currentItemChanged.connect(self._on_msg_selected)
        left_layout.addWidget(self._msg_tree)

        splitter.addWidget(left_panel)

        # -- Right panel: signal table --
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        right_layout.addWidget(QLabel("<b>Signals</b>"))

        self._signal_table = QTableView()
        self._signal_model = SignalTableModel(self._session, self)
        self._signal_table.setModel(self._signal_model)
        self._signal_table.setAlternatingRowColors(True)
        self._signal_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self._signal_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._signal_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._signal_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._signal_table.customContextMenuRequested.connect(self._on_signal_context_menu)
        right_layout.addWidget(self._signal_table)

        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _setup_statusbar(self) -> None:
        self._status_label = QLabel("Ready")
        self.statusBar().addWidget(self._status_label)

    # ------------------------------------------------------------------
    # File actions
    # ------------------------------------------------------------------

    def _on_new(self) -> None:
        reply = QMessageBox.question(
            self,
            "New Database",
            "Discard unsaved changes and create a new database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._session.new_database()
        self._refresh_message_tree()
        self._signal_model.set_message(None)
        self._update_title()
        self._status_label.setText(result.message)

    def _on_open_toml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open TOML", "", "TOML Files (*.toml);;All Files (*)"
        )
        if not path:
            return
        self._open_and_display(path)

    def _on_open_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        self._open_and_display(path)

    def _on_open_xml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open XML", "", "XML Files (*.xml);;All Files (*)"
        )
        if not path:
            return
        self._open_and_display(path)

    def _on_import_dbc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import DBC", "", "DBC Files (*.dbc);;All Files (*)"
        )
        if not path:
            return
        self._open_and_display(path)

    def _open_and_display(self, path: str) -> None:
        result = self._session.open_file(path)
        if not result.success:
            QMessageBox.critical(self, "Open Error", result.message)
            return
        self._refresh_message_tree()
        self._update_title()
        self._status_label.setText(result.message)

    def _on_save(self) -> None:
        path = None
        if self._session.current_filepath and self._session.current_filepath.endswith(".toml"):
            path = self._session.current_filepath
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save TOML", "untitled.toml", "TOML Files (*.toml)"
            )
            if not path:
                return
        result = self._session.save(path)
        if not result.success:
            QMessageBox.critical(self, "Save Error", result.message)
            return
        self._update_title()
        self._status_label.setText(result.message)

    def _on_save_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON", "untitled.json", "JSON Files (*.json)"
        )
        if not path:
            return
        result = self._session.save_as(path, "json")
        if not result.success:
            QMessageBox.critical(self, "Save Error", result.message)
            return
        self._status_label.setText(result.message)

    def _on_save_xml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save XML", "untitled.xml", "XML Files (*.xml)"
        )
        if not path:
            return
        result = self._session.save_as(path, "xml")
        if not result.success:
            QMessageBox.critical(self, "Save Error", result.message)
            return
        self._status_label.setText(result.message)

    def _on_export_dbc(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DBC", "untitled.dbc", "DBC Files (*.dbc)"
        )
        if not path:
            return
        result = self._session.export_dbc(path)
        if not result.success:
            QMessageBox.critical(self, "Export Error", result.message)
            return
        self._status_label.setText(result.message)

    # ------------------------------------------------------------------
    # Message tree
    # ------------------------------------------------------------------

    def _refresh_message_tree(self) -> None:
        self._msg_tree.clear()
        db = self._session.database
        for msg_id in sorted(db.messages.keys()):
            msg = db.messages[msg_id]
            item = QTreeWidgetItem()
            item.setText(0, f"0x{msg.id:X}")
            item.setText(1, msg.name)
            item.setText(2, str(msg.dlc))
            item.setData(0, self._MSG_ID_ROLE, msg.id)
            self._msg_tree.addTopLevelItem(item)
        for col in range(3):
            self._msg_tree.resizeColumnToContents(col)

    def _on_msg_selected(self, current: QTreeWidgetItem, previous: QTreeWidgetItem) -> None:
        if current is None:
            self._signal_model.set_message(None)
            return
        msg_id = current.data(0, self._MSG_ID_ROLE)
        if msg_id is None:
            self._signal_model.set_message(None)
            return
        msg = self._session.database.messages.get(msg_id)
        self._signal_model.set_message(msg)

    def _on_msg_context_menu(self, pos: Any) -> None:
        item = self._msg_tree.itemAt(pos)
        menu = QMenu(self)
        act_add = menu.addAction("Add Message …")
        act_add.triggered.connect(self._on_add_message)
        if item is not None:
            act_edit = menu.addAction("Edit Message …")
            act_edit.triggered.connect(lambda: self._on_edit_message(item))
            act_copy = menu.addAction("Duplicate Message")
            act_copy.triggered.connect(lambda: self._on_duplicate_message(item))
            menu.addSeparator()
            act_del = menu.addAction("Delete Message")
            act_del.triggered.connect(lambda: self._on_delete_message(item))
        menu.exec(self._msg_tree.viewport().mapToGlobal(pos))

    def _on_add_message(self) -> None:
        dlg = MessageDialog(parent=self)
        if dlg.exec() != MessageDialog.DialogCode.Accepted:
            return
        msg = dlg.get_message()
        if msg.id in self._session.database.messages:
            reply = QMessageBox.question(
                self, "Duplicate ID",
                f"Message ID 0x{msg.id:X} already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            result = self._session.force_add_message(msg)
        else:
            result = self._session.add_message(msg)
        self._refresh_message_tree()
        self._status_label.setText(result.message)

    def _on_edit_message(self, item: QTreeWidgetItem) -> None:
        msg_id = item.data(0, self._MSG_ID_ROLE)
        msg = self._session.database.messages.get(msg_id)
        if msg is None:
            return
        dlg = MessageDialog(message=msg, parent=self)
        if dlg.exec() != MessageDialog.DialogCode.Accepted:
            return
        updated = dlg.get_message()
        db = self._session.database
        if updated.id != msg_id and updated.id in db.messages:
            reply = QMessageBox.question(
                self, "Duplicate ID",
                f"Target ID 0x{updated.id:X} already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            db.messages.pop(msg_id, None)
            db.messages[updated.id] = updated
        else:
            db.messages.pop(msg_id, None)
            db.messages[updated.id] = updated
        self._session._modified = True
        self._refresh_message_tree()
        self._status_label.setText(f"Updated message: 0x{updated.id:X} {updated.name}")

    def _on_duplicate_message(self, item: QTreeWidgetItem) -> None:
        msg_id = item.data(0, self._MSG_ID_ROLE)
        msg = self._session.database.messages.get(msg_id)
        if msg is None:
            return
        new_id = msg.id + 1
        while new_id in self._session.database.messages:
            new_id += 1
        # Deep copy signals to avoid sharing Signal objects between messages
        import copy
        new_msg = Message(
            id=new_id,
            name=f"{msg.name}_copy",
            dlc=msg.dlc,
            cycle_time=msg.cycle_time,
            comment=msg.comment,
            sender=msg.sender,
            signals=[copy.deepcopy(sig) for sig in msg.signals],
        )
        self._session.force_add_message(new_msg)
        self._refresh_message_tree()
        self._status_label.setText(f"Duplicated: 0x{msg.id:X} → 0x{new_id:X}")

    def _on_delete_message(self, item: QTreeWidgetItem) -> None:
        msg_id = item.data(0, self._MSG_ID_ROLE)
        msg = self._session.database.messages.get(msg_id)
        if msg is None:
            return
        reply = QMessageBox.question(
            self, "Delete Message",
            f"Delete message 0x{msg_id:X} '{msg.name}' and its {len(msg.signals)} signal reference(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._session.remove_message(msg_id)
        self._refresh_message_tree()
        self._signal_model.set_message(None)
        self._status_label.setText(result.message)

    # ------------------------------------------------------------------
    # Signal operations
    # ------------------------------------------------------------------

    def _on_signal_context_menu(self, pos: Any) -> None:
        menu = QMenu(self)
        act_add = menu.addAction("Add Signal …")
        act_add.triggered.connect(self._on_add_signal)
        idx = self._signal_table.indexAt(pos)
        if idx.isValid():
            act_edit = menu.addAction("Edit Signal …")
            act_edit.triggered.connect(lambda: self._on_edit_signal(idx.row()))
            menu.addSeparator()
            act_del = menu.addAction("Delete Signal")
            act_del.triggered.connect(lambda: self._on_delete_signal(idx.row()))
        menu.exec(self._signal_table.viewport().mapToGlobal(pos))

    def _on_add_signal(self) -> None:
        if self._signal_model.message is None:
            QMessageBox.information(self, "No Message", "Select a message first.")
            return
        dlg = SignalDialog(parent=self)
        if dlg.exec() != SignalDialog.DialogCode.Accepted:
            return
        sig = dlg.get_signal()
        msg_id = self._signal_model.message.id
        result = self._session.add_signal(msg_id, sig)
        # Session.add_signal already appends to Message.signals via
        # database.add_signal_to_message, so only notify the model.
        self._signal_model.notify_signal_appended()
        self._status_label.setText(result.message)

    def _on_edit_signal(self, row: int) -> None:
        if self._signal_model.message is None:
            return
        if not (0 <= row < len(self._signal_model.message.signals)):
            return
        # In per-message model, signals list contains Signal objects directly
        sig = self._signal_model.message.signals[row]
        if sig is None:
            return
        dlg = SignalDialog(signal=sig, parent=self)
        if dlg.exec() != SignalDialog.DialogCode.Accepted:
            return
        updated = dlg.get_signal()
        # If name changed, update the signal in the message's signals list
        if updated.name != sig.name:
            self._signal_model.message.signals[row] = updated
        # Signal object is already updated in-place if editing existing signal
        self._signal_model.dataChanged.emit(
            self._signal_model.index(row, 0),
            self._signal_model.index(row, self._signal_model.columnCount() - 1),
            [],
        )
        self._signal_model.data_changed.emit()
        self._session._modified = True
        self._status_label.setText(f"Updated signal: {updated.name}")

    def _on_delete_signal(self, row: int) -> None:
        if self._signal_model.message is None:
            return
        if not (0 <= row < len(self._signal_model.message.signals)):
            return
        # In per-message model, get signal object directly
        sig = self._signal_model.message.signals[row]
        sig_name = sig.name if sig else f"signal[{row}]"
        reply = QMessageBox.question(
            self, "Delete Signal",
            f"Remove signal '{sig_name}' from this message?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        msg_id = self._signal_model.message.id
        result = self._session.remove_signal(msg_id, sig_name)
        # Session.remove_signal already removed from Message.signals via
        # database.remove_signal_from_message, so only notify the model.
        self._signal_model.notify_signal_removed(row)
        self._status_label.setText(result.message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_title(self) -> None:
        fpath = self._session.current_filepath
        if fpath:
            self.setWindowTitle(f"CanMatrix Editor - {os.path.basename(fpath)}")
        else:
            self.setWindowTitle("CanMatrix Editor - Untitled")