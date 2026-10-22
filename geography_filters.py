"""Общие зависимые списки географии для таблиц и аналитических отчётов."""
from nir_operations import read_rows

GEOGRAPHY_FIELDS = (("region", "Округ"), ("oblname", "Субъект РФ"),
                    ("city", "Город"), ("codvuz", "Вуз"))


def populate_geography(combos, path, values=None, after=None):
    fields = list(combos)
    values = values if values is not None else {f: c.currentData() for f, c in combos.items()}
    start = fields.index(after) + 1 if after is not None else 0
    for index, field in enumerate(fields):
        if index < start:
            continue
        conditions, parameters = [], []
        for parent in fields[:index]:
            value = combos[parent].currentData()
            if value is not None:
                conditions.append(f"{parent} = ?")
                parameters.append(value)
        conditions.append(f"{field} IS NOT NULL AND {field} != ''")
        label = "COALESCE(NULLIF(z2,''),z1)" if field == "codvuz" else field
        rows = read_rows(f"SELECT DISTINCT {field} AS value, {label} AS label FROM vuz "
                         f"WHERE {' AND '.join(conditions)} ORDER BY {field}", tuple(parameters), path=path)
        combo = combos[field]
        blocked = combo.blockSignals(True)
        combo.clear()
        combo.addItem("Все", None)
        for row in rows:
            text = f"{row['value']} — {row['label']}" if field == "codvuz" else row['label']
            combo.addItem(text, row['value'])
        combo.setCurrentIndex(max(0, combo.findData(values.get(field))))
        combo.blockSignals(blocked)
