from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtSql import QSqlDatabase, QSqlQuery, QSqlTableModel
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from database import DB_PATH, create_database, rebuild_financing, run_validation


TABLE_CONFIG = {
    "nir": {
        "title": "НИР",
        "headers": {
            "id": "ID",
            "codvuz": "Код вуза",
            "rnw": "Регистрационный номер",
            "f1": "Характер НИР",
            "z2": "Вуз (кратко)",
            "f6": "Руководитель (ФИО)",
            "f10": "Код(ы) ГРНТИ",
            "f2": "Наименование НИР",
            "f7": "Должность руководителя",
            "f18": "Плановое финансирование, руб.",
        },
        "editable": {"codvuz", "rnw", "f1", "f6", "f10", "f2", "f7", "f18"},
        "hint": "Подсказка: руководителя вводить в формате Фамилия И.О.; RNW — без пробелов; ГРНТИ — один или два кода через ';'.",
    },
    "financing": {
        "title": "Финансирование вузов",
        "headers": {
            "codvuz": "Код вуза",
            "z2": "Вуз (кратко)",
            "z3": "План, руб.",
            "z18": "Факт, руб.",
            "numworks": "Количество НИР",
        },
        "editable": {"z18"},
        "hint": "План и количество НИР рассчитываются автоматически. Вручную изменяется только фактическое финансирование.",
    },
    "vuz": {
        "title": "Справочник вузов",
        "headers": {
            "codvuz": "Код вуза",
            "z1": "Наименование",
            "z1full": "Полное юридическое наименование",
            "z2": "Сокращенное наименование",
            "region": "Федеральный округ",
            "city": "Город",
            "status": "Статус",
            "obl": "Код субъекта",
            "oblname": "Субъект РФ",
            "gr_ved": "Группа ведомств",
            "prof": "Профиль",
        },
        "editable": set(),
        "hint": "VUZ — справочник: только просмотр. Изменение из интерфейса ЛР №1 запрещено.",
    },
    "grnti": {
        "title": "Рубрики ГРНТИ",
        "headers": {"codrub": "Код рубрики", "rubrika": "Наименование рубрики"},
        "editable": set(),
        "hint": "Справочник рубрик используется для автоматической проверки и анализа кодов ГРНТИ.",
    },
}


class ControlledTableModel(QSqlTableModel):
    """QSqlTableModel, в котором редактируются только разрешенные поля."""

    def __init__(self, editable_fields: set[str], parent=None, db=QSqlDatabase()):
        super().__init__(parent, db)
        self.editable_fields = editable_fields

    def flags(self, index):
        flags = super().flags(index)
        if not index.isValid():
            return flags
        field = self.record().fieldName(index.column())
        if field not in self.editable_fields:
            return flags & ~Qt.ItemFlag.ItemIsEditable
        return flags | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.isValid():
            field = self.record().fieldName(index.column())
            text = str(value).strip() if value is not None else ""
            if field == "rnw":
                value = "".join(text.split())
            elif field == "f10":
                value = "; ".join(p.strip() for p in text.replace(",", ";").split(";") if p.strip())
            elif field in {"f18", "z18"}:
                try:
                    value = int(float(text.replace(" ", "").replace(",", ".")))
                except ValueError:
                    QMessageBox.warning(None, "Некорректное значение", "Сумма должна быть целым числом рублей.")
                    return False
            elif field == "f1":
                value = text.upper()
                if value not in {"Ф", "П", "Р"}:
                    QMessageBox.warning(None, "Некорректное значение", "Характер НИР: только Ф, П или Р.")
                    return False
            else:
                value = text
        return super().setData(index, value, role)


class TablePage(QWidget):
    def __init__(self, db: QSqlDatabase, table_name: str, parent=None):
        super().__init__(parent)
        self.table_name = table_name
        cfg = TABLE_CONFIG[table_name]

        self.model = ControlledTableModel(cfg["editable"], self, db)
        self.model.setTable(table_name)
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnManualSubmit)
        self.model.select()

        self.field_names: list[str] = []
        rec = self.model.record()
        for col in range(rec.count()):
            field = rec.fieldName(col)
            self.field_names.append(field)
            self.model.setHeaderData(col, Qt.Orientation.Horizontal, cfg["headers"].get(field, field))

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.resizeColumnsToContents()

        self.search_field = QComboBox()
        for field in self.field_names:
            self.search_field.addItem(cfg["headers"].get(field, field), field)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Введите текст для фильтрации...")
        self.search_edit.textChanged.connect(self.apply_filter)

        clear_btn = QPushButton("Сбросить фильтр")
        clear_btn.clicked.connect(self.clear_filter)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Поиск по полю:"))
        search_row.addWidget(self.search_field)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(clear_btn)

        hint = QLabel(cfg["hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; padding: 4px 0;")

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(search_row)
        layout.addWidget(self.view, 1)

    def apply_filter(self, text: str):
        field = self.search_field.currentData()
        if not field:
            return
        text = text.strip().replace("'", "''")
        if not text:
            self.model.setFilter("")
        else:
            self.model.setFilter(f"CAST({field} AS TEXT) LIKE '%{text}%'")
        self.model.select()

    def clear_filter(self):
        self.search_edit.clear()
        self.model.setFilter("")
        self.model.select()

    def save(self) -> bool:
        return self.model.submitAll()

    def revert(self):
        self.model.revertAll()
        self.model.select()

    def refresh(self):
        self.model.select()
        self.view.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("СУБД — вариант 9: тематический план НИР")
        self.resize(1450, 820)

        self.db = self.connect_db(DB_PATH)
        self.tabs = QTabWidget()
        self.pages: dict[str, TablePage] = {}
        for name in ("nir", "financing", "vuz", "grnti"):
            page = TablePage(self.db, name)
            self.pages[name] = page
            self.tabs.addTab(page, TABLE_CONFIG[name]["title"])
        self.setCentralWidget(self.tabs)

        self.build_menu()
        self.statusBar().showMessage("Готово")

        # Автоматическая проверка — по замечанию преподавателя.
        self.auto_check(show_dialog=False)

    @staticmethod
    def connect_db(path: Path) -> QSqlDatabase:
        db = QSqlDatabase.addDatabase("QSQLITE")
        # Ждем до 30 секунд, если SQLite кратковременно занят другой операцией.
        db.setConnectOptions("QSQLITE_BUSY_TIMEOUT=30000")
        db.setDatabaseName(str(path))
        if not db.open():
            raise RuntimeError(f"Не удалось открыть БД: {path}\n{db.lastError().text()}")

        # WAL снимает конфликт «Qt читает / sqlite3 пишет», который и давал
        # ошибку 'database is locked' в первой версии проекта.
        q = QSqlQuery(db)
        for pragma in (
            "PRAGMA busy_timeout = 30000",
            "PRAGMA foreign_keys = ON",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
        ):
            if not q.exec(pragma):
                raise RuntimeError(f"Не удалось выполнить {pragma}: {q.lastError().text()}")
        return db

    def build_menu(self):
        menu_data = self.menuBar().addMenu("Данные")
        a_save = menu_data.addAction("Сохранить изменения")
        a_save.setShortcut("Ctrl+S")
        a_save.triggered.connect(self.save_all)
        a_revert = menu_data.addAction("Отменить несохраненные изменения")
        a_revert.triggered.connect(self.revert_all)
        menu_data.addSeparator()
        a_recalc = menu_data.addAction("Пересчитать финансирование")
        a_recalc.triggered.connect(self.recalculate_financing)
        a_check = menu_data.addAction("Автоматическая проверка данных")
        a_check.triggered.connect(lambda: self.auto_check(show_dialog=True))

        menu_analysis = self.menuBar().addMenu("Анализ")
        for title in (
            "Распределение НИР по вузам",
            "Распределение по рубрикам ГРНТИ",
            "Распределение по характеру НИР",
        ):
            action = menu_analysis.addAction(title)
            action.triggered.connect(lambda checked=False, t=title: self.analysis_placeholder(t))

        menu_help = self.menuBar().addMenu("Помощь")
        a_help = menu_help.addAction("Справка")
        a_help.triggered.connect(self.show_help)
        a_about = menu_help.addAction("О программе")
        a_about.triggered.connect(self.show_about)

        a_exit = self.menuBar().addAction("Выход")
        a_exit.triggered.connect(self.close)

    def save_all(self):
        failed = []
        for name, page in self.pages.items():
            if TABLE_CONFIG[name]["editable"] and not page.save():
                failed.append(name)
        if failed:
            QMessageBox.critical(self, "Ошибка сохранения", "Не удалось сохранить: " + ", ".join(failed))
            return
        self.recalculate_financing(show_message=False)
        self.auto_check(show_dialog=False)
        self.statusBar().showMessage("Изменения сохранены, финансирование пересчитано, проверка выполнена.", 7000)

    def revert_all(self):
        for page in self.pages.values():
            page.revert()
        self.statusBar().showMessage("Несохраненные изменения отменены.", 5000)

    def recalculate_financing(self, show_message=True):
        # WAL + busy_timeout позволяют безопасно пересчитывать таблицу через
        # отдельное sqlite3-соединение при открытом интерфейсе Qt.
        try:
            rebuild_financing()
        except sqlite3.OperationalError as exc:
            QMessageBox.critical(
                self,
                "Ошибка базы данных",
                "Не удалось пересчитать финансирование.\n\n"
                f"{exc}\n\n"
                "Закройте вторую копию программы и программы просмотра SQLite, "
                "если они открыты, затем повторите.",
            )
            return False
        self.pages["financing"].refresh()
        if show_message:
            QMessageBox.information(self, "Пересчет", "Таблица финансирования пересчитана по текущим данным НИР.")
        return True

    def auto_check(self, show_dialog=True):
        try:
            # В интерфейсе проверка только читает БД. Журнал уже формируется
            # при первичном создании базы; лишняя запись здесь не нужна.
            issues = run_validation(write_log=False)
        except sqlite3.OperationalError as exc:
            if show_dialog:
                QMessageBox.critical(self, "Ошибка проверки", str(exc))
            self.statusBar().showMessage(f"Проверка не выполнена: {exc}", 7000)
            return
        errors = sum(1 for i in issues if i[0] == "ERROR")
        warnings = sum(1 for i in issues if i[0] == "WARNING")
        self.statusBar().showMessage(f"Автопроверка: ошибок — {errors}, предупреждений — {warnings}")
        if not show_dialog:
            return
        if not issues:
            QMessageBox.information(self, "Проверка данных", "Ошибок и предупреждений не найдено.")
            return
        lines = [f"{sev}: {ref} — {msg}" for sev, _table, ref, msg in issues[:30]]
        if len(issues) > 30:
            lines.append(f"... еще {len(issues) - 30} сообщений")
        QMessageBox.warning(
            self,
            "Проверка данных",
            f"Найдено ошибок: {errors}; предупреждений: {warnings}.\n\n" + "\n".join(lines),
        )

    def analysis_placeholder(self, title: str):
        QMessageBox.information(
            self,
            title,
            "Пункт меню предусмотрен в общей оболочке. Детальная реализация аналитического отчета относится к последующим лабораторным работам.",
        )

    def show_help(self):
        QMessageBox.information(
            self,
            "Справка",
            "ЛР №1, вариант 9.\n\n"
            "• Данные отображаются во вкладках.\n"
            "• VUZ и ГРНТИ — только просмотр.\n"
            "• RNW сохраняется без пробелов.\n"
            "• Один или два кода ГРНТИ вводятся через ';'. Запятая автоматически заменяется.\n"
            "• Денежные суммы хранятся целыми рублями.\n"
            "• После сохранения выполняются пересчет финансирования и автоматическая проверка.",
        )

    def show_about(self):
        QMessageBox.information(
            self,
            "О программе",
            "Учебная оболочка информационной системы\n"
            "«Управление научными исследованиями по тематическому плану»\n"
            "Вариант №9, НИУ «МЭИ», 2026.",
        )

    def closeEvent(self, event):
        # На случай несохраненных ручных изменений даем стандартный выбор.
        reply = QMessageBox.question(
            self,
            "Выход",
            "Сохранить изменения перед выходом?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if reply == QMessageBox.StandardButton.Yes:
            self.save_all()
        self.db.close()
        event.accept()


def main():
    create_database(force=False)
    app = QApplication(sys.argv)
    app.setApplicationName("СУБД ЛР1 — вариант 9")
    try:
        window = MainWindow()
    except Exception as exc:
        QMessageBox.critical(None, "Ошибка запуска", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
