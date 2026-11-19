"""Крок 1: вибір ТЗ, короткий огляд і налаштування запуску."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core.brief import BriefError, load_brief
from ..core.style import list_styles

MAX_RECENT = 8


def _slot_text(i: int, s) -> str:
    if s.clip:
        kind = f"{s.clip} {s.start or 0:g}–{s.end if s.end is not None else 'кінець'} с"
    elif s.find:
        kind = f"фраза «{s.find}»"
    else:
        kind = "будь-який кадр" + (f" з {s.from_}" if s.from_ else "")
    extra = f" · {s.duration:g} с" if s.duration else ""
    title = f" — «{s.title}»" if s.title else ""
    return f"{i}. {kind}{extra}{title}"


class StartPage(QWidget):
    start_requested = Signal(Path, dict)   # шлях до ТЗ, опції generate
    open_results = Signal(Path)            # папка з готовими варіаціями

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.brief_path: Path | None = None

        title = QLabel("MemoCut")
        title.setObjectName("h1")
        hint = QLabel("Виберіть ТЗ (файл .yaml) — програма сама змонтує кілька варіацій відео.")
        hint.setObjectName("muted")

        pick = QPushButton("Вибрати ТЗ…")
        pick.setObjectName("primary")
        pick.clicked.connect(self._pick)
        opened = QPushButton("Відкрити готові результати…")
        opened.clicked.connect(self._pick_results)
        top = QHBoxLayout()
        top.addWidget(pick)
        top.addWidget(opened)
        top.addStretch()

        self.recent = QListWidget()
        self.recent.itemClicked.connect(lambda it: self.load(Path(it.data(Qt.UserRole))))

        # --- огляд ТЗ ---
        self.card = QFrame()
        self.card.setObjectName("card")
        self.b_name = QLabel()
        self.b_name.setObjectName("h2")
        self.b_info = QLabel()
        self.b_info.setObjectName("muted")
        self.b_info.setWordWrap(True)
        self.b_slots = QLabel()
        self.b_slots.setWordWrap(True)
        self.b_slots.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.style_box = QComboBox()
        self.style_box.addItems(list_styles())
        self.var_box = QSpinBox()
        self.var_box.setRange(1, 6)
        self.no_tr = QCheckBox("Без розпізнавання мови (швидше; пошук фраз працює лише з .srt/.words.json)")
        form = QFormLayout()
        form.addRow("Стиль:", self.style_box)
        form.addRow("Варіацій:", self.var_box)
        form.addRow("", self.no_tr)

        self.go = QPushButton("Змонтувати")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._start)
        self.err = QLabel()
        self.err.setObjectName("error")
        self.err.setWordWrap(True)

        cl = QVBoxLayout(self.card)
        cl.addWidget(self.b_name)
        cl.addWidget(self.b_info)
        cl.addWidget(self.b_slots)
        cl.addLayout(form)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.go)
        cl.addLayout(row)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addSpacing(8)
        lay.addLayout(top)
        self.recent_label = QLabel("Нещодавні ТЗ")
        self.recent_label.setObjectName("muted")
        lay.addWidget(self.recent_label)
        lay.addWidget(self.recent)
        lay.addWidget(self.err)
        lay.addWidget(self.card)
        lay.addStretch()

        self.card.hide()
        self._fill_recent()

    # ---- нещодавні ----
    def _recent_list(self) -> list[str]:
        v = self.settings.value("recent_briefs", [])
        if isinstance(v, str):
            v = [v]
        out: list[str] = []
        for p in v or []:
            if Path(p).is_file() and Path(p).is_absolute() and p not in out:
                out.append(p)
        return out

    def _fill_recent(self) -> None:
        self.recent.clear()
        items = self._recent_list()
        for p in items:
            it = QListWidgetItem(f"{Path(p).name}    —    {Path(p).parent}")
            it.setData(Qt.UserRole, p)
            self.recent.addItem(it)
        self.recent.setFixedHeight(min(len(items), 5) * 30 + 8)
        self.recent.setVisible(bool(items))
        self.recent_label.setVisible(bool(items))

    def _remember(self, path: Path) -> None:
        path = path.resolve()
        items = [str(path)] + [p for p in self._recent_list() if p != str(path)]
        self.settings.setValue("recent_briefs", items[:MAX_RECENT])
        self._fill_recent()

    # ---- дії ----
    def _pick(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()))
        f, _ = QFileDialog.getOpenFileName(self, "Виберіть ТЗ", start, "ТЗ (*.yaml *.yml)")
        if f:
            self.settings.setValue("last_dir", str(Path(f).parent))
            self.load(Path(f))

    def _pick_results(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()))
        d = QFileDialog.getExistingDirectory(self, "Папка з результатами (де лежать var1, var2…)", start)
        if d:
            self.open_results.emit(Path(d))

    def load(self, path: Path) -> bool:
        """Прочитати ТЗ і показати огляд. Повертає False, якщо ТЗ з помилкою."""
        self.err.clear()
        try:
            b = load_brief(path)
        except (BriefError, OSError, ValueError) as e:
            self.card.hide()
            self.err.setText(f"Не вдалося прочитати ТЗ {path.name}:\n{e}")
            return False
        except Exception as e:  # напр. синтаксична помилка YAML
            self.card.hide()
            self.err.setText(f"ТЗ {path.name} містить помилку:\n{e}")
            return False
        self.brief_path = path
        self._remember(path)
        src = b.source_path()
        exists = src.is_dir()
        self.b_name.setText(b.name)
        self.b_info.setText(
            f"Формат {b.format} · сегментів {len(b.slots)}"
            + (f" · фінальна картка «{b.cta}»" if b.cta else "")
            + f"\nВідео з: {src}" + ("" if exists else "  ⚠ папку не знайдено"))
        self.b_slots.setText("\n".join(_slot_text(i, s) for i, s in enumerate(b.slots, 1)))
        styles = list_styles()
        if b.style not in styles:
            self.err.setText(f"Стиль «{b.style}» із ТЗ не знайдено — виберіть інший.")
        idx = self.style_box.findText(b.style)
        self.style_box.setCurrentIndex(max(0, idx))
        self.var_box.setValue(max(1, min(6, b.variations)))
        self.go.setEnabled(exists)
        if not exists:
            self.err.setText(f"Папку з відео не знайдено: {src}\nВиправте source_dir у ТЗ.")
        self.card.show()
        return True

    def _start(self) -> None:
        if not self.brief_path:
            return
        opts = {"style": self.style_box.currentText() or None,
                "variations": self.var_box.value(),
                "transcripts": not self.no_tr.isChecked()}
        self.start_requested.emit(self.brief_path, opts)
