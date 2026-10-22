"""Диалог НИР и просмотр журнала изменений."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout,
)

from nir_operations import normalize_grnti_input, read_rows, save_nir


class NirDialog(QDialog):
    def __init__(self, path: Path, row: dict | None = None, parent=None):
        super().__init__(parent)
        self.path, self.original = path, row
        self.saved_id = None
        self.setWindowTitle("Изменить НИР" if row else "Добавить НИР")
        self.resize(680, 510)
        self.vuz = QComboBox()
        self.vuz.addItem("Выберите вуз…", None)
        for v in read_rows("SELECT codvuz,z2,z1 FROM vuz ORDER BY codvuz", path=path):
            self.vuz.addItem(f"{v['codvuz']} — {v['z2'] or v['z1']}", v["codvuz"])
        self.rnw = QLineEdit()
        self.rnw.setPlaceholderText("Введите номер без пробелов")
        self.rnw.setToolTip("Введите регистрационный номер в формате вуза. Буквы и ведущие нули сохраняются.")
        self.rnw.textEdited.connect(self.strip_number_spaces)
        self.character = QComboBox()
        self.character.addItem("Выберите характер…", None)
        for code, name in (("Ф", "Фундаментальная"), ("П", "Прикладная"), ("Р", "Разработка")):
            self.character.addItem(f"{code} — {name}", code)
        self.title = QTextEdit()
        self.title.setAcceptRichText(False)
        self.title.setMaximumHeight(100)
        self.leader = QLineEdit()
        self.leader.setPlaceholderText("Например, Иванов И.И.; другой формат имени допустим")
        self.position = QLineEdit()
        self.grnti_first, self.grnti_second = QLineEdit(), QLineEdit()
        for edit in (self.grnti_first, self.grnti_second):
            edit.setInputMask("00.00.00;_")
        self.money = QLineEdit("0")
        self.money.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{1,19}"), self))
        form = QFormLayout()
        for label, widget in (
            ("Вуз", self.vuz), ("Рег. номер", self.rnw), ("Характер НИР", self.character),
            ("Наименование НИР", self.title), ("Руководитель", self.leader),
            ("Должность руководителя (обязательно)", self.position), ("Первый код ГРНТИ", self.grnti_first),
            ("Второй код ГРНТИ (необязательно)", self.grnti_second),
            ("Плановое финансирование, руб.", self.money),
        ):
            form.addRow(label, widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.hide()
        layout.addWidget(self.note)
        layout.addWidget(buttons)
        if row:
            index = self.vuz.findData(row["codvuz"])
            if index < 0:
                self.vuz.addItem(f"{row['codvuz']} — отсутствует в справочнике", row["codvuz"])
                index = self.vuz.count() - 1
            self.vuz.setCurrentIndex(index)
            self.rnw.setText(row["rnw"] or "")
            self.character.setCurrentIndex(self.character.findData(row["f1"]))
            self.title.setPlainText(row["f2"] or "")
            self.leader.setText(row["f6"] or "")
            self.position.setText(row["f7"] or "")
            normalized = normalize_grnti_input(row["f10"] or "")
            codes = normalized.split(";")
            self.grnti_first.setText(codes[0].strip())
            if len(codes) > 1:
                self.grnti_second.setText(codes[1].strip())
            self.money.setText(str(row["f18"]))
            if normalized != (row["f10"] or ""):
                self.note.setText("Исходная запись ГРНТИ: " + (row["f10"] or "") +
                                  ". При сохранении формат будет приведён к XX.XX.XX; YY.YY.YY.")
                self.note.show()

    def strip_number_spaces(self, text: str):
        cleaned = "".join(text.split())
        if text != cleaned:
            cursor = len("".join(text[:self.rnw.cursorPosition()].split()))
            self.rnw.setText(cleaned)
            self.rnw.setCursorPosition(cursor)

    def values(self) -> dict:
        codes = [self.grnti_first.text()]
        if self.grnti_second.text().replace(".", ""):
            codes.append(self.grnti_second.text())
        return {
            "codvuz": self.vuz.currentData(), "rnw": self.rnw.text(),
            "f1": self.character.currentData(), "f2": self.title.toPlainText(),
            "f6": self.leader.text(), "f7": self.position.text(),
            "f10": "; ".join(codes), "f18": self.money.text(),
        }

    def save(self):
        try:
            self.saved_id = save_nir(self.values(), self.original["id"] if self.original else None,
                                     path=self.path, expected=self.original)
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "НИР не сохранена", str(exc))
            return
        self.accept()


class ChangeLogDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Журнал изменений")
        self.resize(1000, 640)
        self.rows = read_rows("SELECT * FROM change_log ORDER BY id DESC", path=path)
        table = QTableWidget(len(self.rows), 5)
        table.setHorizontalHeaderLabels(["Дата и время", "Действие", "Таблица", "Запись", "Рег. номер / вуз"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        names = {"INSERT": "Добавление", "UPDATE": "Изменение", "DELETE": "Удаление"}
        for i, row in enumerate(self.rows):
            snapshot = json.loads(row["after_data"] or row["before_data"])
            timestamp = datetime.fromisoformat(row["changed_at"].replace("Z", "+00:00")).astimezone()
            values = [timestamp.strftime("%d.%m.%Y %H:%M:%S"), names[row["operation"]],
                      "НИР" if row["table_name"] == "nir" else "Финансирование",
                      str(row["row_id"]), f"{snapshot.get('rnw', '—')} / {snapshot['codvuz']}"]
            for j, value in enumerate(values):
                table.setItem(i, j, QTableWidgetItem(value))
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        table.currentCellChanged.connect(self.show_details)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Время показано в часовом поясе компьютера. Выберите операцию для просмотра значений."))
        layout.addWidget(table, 2)
        layout.addWidget(self.details, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        if self.rows:
            table.setCurrentCell(0, 0)

    def show_details(self, current_row, *_):
        if current_row < 0:
            return
        row = self.rows[current_row]
        parts = []
        if row.get("reason"):
            parts.append("Причина изменения:\n" + row["reason"])
        for label, field in (("До изменения", "before_data"), ("После изменения", "after_data")):
            parts.append(label + ":\n" +
                         (json.dumps(json.loads(row[field]), ensure_ascii=False, indent=2) if row[field] else "—"))
        self.details.setPlainText("\n\n".join(parts))
