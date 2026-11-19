"""Крок 1: ТЗ прямо в програмі.

Вкладка «ТЗ» — форма: папка гри, назва/формат/стиль, сцени (перша — хук), тексти поверх відео,
музика, вільний текст від замовника. Вкладка «Файл ТЗ (YAML)» — те саме як текст: можна
скопіювати, зберегти, передати іншій людині, відкрити й поправити руками.

Форма і YAML працюють з одним словником (як у файлі ТЗ): form_data() / set_form_data().
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from ..analyze.catalog import list_videos
from ..core.brief import BriefError, brief_to_yaml, brief_from_text, load_brief_data, parse_brief
from ..core.library import GameFolder
from ..core.project import safe_name
from ..core.style import list_styles
from .settings_dialog import cached_voices, tts_config

MAX_RECENT = 8
FORMATS = [("9x16", "9:16 — Reels / TikTok / Shorts"), ("4x5", "4:5 — стрічка Instagram"),
           ("1x1", "1:1 — квадрат"), ("16x9", "16:9 — YouTube")]
KINDS = [("any", "Найкращий кадр (програма підбере)"),
         ("find", "Момент, де кажуть фразу"),
         ("clip", "Конкретне відео (ID з каталогу або файл)")]
WORK = "MemoCut"  # папка в грі: ТЗ/ і Результати/


def project_base(source: Path) -> Path:
    """Куди класти ТЗ і результати: у корінь гри, а для звичайної папки — в неї саму."""
    g = GameFolder.detect(source)
    return (g.root if g else source) / WORK


def _card(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 12, 16, 14)
    t = QLabel(title)
    t.setObjectName("h2")
    lay.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("muted")
        h.setWordWrap(True)
        lay.addWidget(h)
    return f, lay


def _seconds(maximum: float = 600, special: str = "авто") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0, maximum)
    s.setDecimals(1)
    s.setSingleStep(0.5)
    s.setSuffix(" с")
    s.setSpecialValueText(special)  # 0 = не задано
    s.setFixedWidth(84)
    return s


class SceneRow(QFrame):
    """Одна сцена ТЗ (слот). Перша в списку — хук."""
    remove_requested = Signal(object)
    move_requested = Signal(object, int)
    changed = Signal()

    def __init__(self, page: "BriefPage"):
        super().__init__()
        self.page = page
        self.setObjectName("scene")
        self.extra: dict = {}  # поля, яких немає у формі (напр. from) — зберігаються як є

        self.num = QLabel()
        self.num.setObjectName("h3")
        self.num.setFixedWidth(70)
        self.kind = QComboBox()
        for k, label in KINDS:
            self.kind.addItem(label, k)
        self.value = QLineEdit()
        self.start = _seconds(special="від")
        self.end = _seconds(special="до")
        self.pick = QPushButton("Файл…")
        self.pick.setToolTip("Вибрати відео з папки гри")
        self.pick.clicked.connect(self._pick_file)
        self.up, self.down, self.rm = QToolButton(), QToolButton(), QToolButton()
        for b, t, tip in ((self.up, "↑", "Вище"), (self.down, "↓", "Нижче"), (self.rm, "✕", "Видалити сцену")):
            b.setText(t)
            b.setToolTip(tip)
            b.setAutoRaise(True)
        self.up.clicked.connect(lambda: self.move_requested.emit(self, -1))
        self.down.clicked.connect(lambda: self.move_requested.emit(self, 1))
        self.rm.clicked.connect(lambda: self.remove_requested.emit(self))

        self.look = QLineEdit()
        self.look.setPlaceholderText("Що має бути в кадрі, напр. «коробка, картки крупно» — шукаю в описах КАТАЛОГу")
        self.look.setToolTip("Програма порівнює ці слова з описами відео в КАТАЛОГ.csv і бере найсхожіші.\n"
                             "На екран цей текст НЕ виводиться.")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Напис, який з'явиться на відео (необов'язково)")
        self.duration = _seconds(60)
        self.duration.setToolTip("Тривалість сцени. «авто» — програма вирішить сама")
        self.subs = QCheckBox("субтитри")
        self.subs.setChecked(True)
        self.subs.setToolTip("Показувати субтитри з мови в цій сцені")

        g = QGridLayout(self)
        g.setContentsMargins(10, 8, 6, 8)
        g.setHorizontalSpacing(8)
        g.addWidget(self.num, 0, 0)
        g.addWidget(self.kind, 0, 1)
        top = QHBoxLayout()
        top.addWidget(self.value, 1)
        top.addWidget(self.start)
        top.addWidget(self.end)
        top.addWidget(self.pick)
        g.addLayout(top, 0, 2)
        btns = QHBoxLayout()
        for b in (self.up, self.down, self.rm):
            btns.addWidget(b)
        g.addLayout(btns, 0, 3)
        self.look_label = QLabel("Що в кадрі:")
        g.addWidget(self.look_label, 1, 0, Qt.AlignRight)
        g.addWidget(self.look, 1, 1, 1, 3)
        g.addWidget(QLabel("Напис:"), 2, 0, Qt.AlignRight)
        bottom = QHBoxLayout()
        bottom.addWidget(self.title, 1)
        bottom.addWidget(QLabel("Тривалість:"))
        bottom.addWidget(self.duration)
        bottom.addWidget(self.subs)
        g.addLayout(bottom, 2, 1, 1, 3)
        g.setColumnStretch(2, 1)

        self.kind.currentIndexChanged.connect(self._kind_changed)
        for w in (self.value, self.title, self.look):
            w.textChanged.connect(self.changed)
        for w in (self.start, self.end, self.duration):
            w.valueChanged.connect(self.changed)
        self.subs.toggled.connect(self.changed)
        self._kind_changed()

    def set_number(self, i: int, total: int) -> None:
        self.num.setText("1 · Хук" if i == 0 else f"{i + 1} · Сцена")
        self.up.setEnabled(i > 0)
        self.down.setEnabled(i < total - 1)
        self.rm.setEnabled(total > 1)

    def _kind_changed(self) -> None:
        k = self.kind.currentData()
        self.value.setVisible(k != "any")
        clip = k == "clip"
        for w in (self.start, self.end, self.pick):
            w.setVisible(clip)
        self.value.setPlaceholderText(
            "Напр. «ми так сміялися» — знайду в транскриптах" if k == "find" else "LUB-UA-041 або IMG_0412.MOV")
        self.duration.setVisible(not clip)
        self.look.setVisible(not clip)
        self.look_label.setVisible(not clip)
        self.changed.emit()

    def _pick_file(self) -> None:
        src = self.page.source_path()
        f, _ = QFileDialog.getOpenFileName(self, "Виберіть відео", str(src or Path.home()),
                                           "Відео (*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.mts)")
        if not f:
            return
        p = Path(f)
        g = self.page.game
        entry = next((e for e in g.entries.values() if (g.root / e.rel) == p), None) if g else None
        if entry and entry.id:
            self.value.setText(entry.id)
        else:
            try:
                self.value.setText(p.relative_to(src).as_posix() if src else p.name)
            except ValueError:
                self.value.setText(str(p))

    # ---- дані ----
    def to_dict(self) -> dict:
        k = self.kind.currentData()
        d: dict = {}
        v = self.value.text().strip()
        if k == "any" or not v:
            d["any"] = True
        elif k == "find":
            d["find"] = v
        else:
            d["clip"] = v
            if self.start.value() > 0:
                d["start"] = round(self.start.value(), 2)
            if self.end.value() > 0:
                d["end"] = round(self.end.value(), 2)
        d.update(self.extra)
        if k != "clip" and self.look.text().strip():
            d["look"] = self.look.text().strip()
        if self.title.text().strip():
            d["title"] = self.title.text().strip().replace(" | ", "\n")
        if self.duration.value() > 0 and k != "clip":
            d["duration"] = round(self.duration.value(), 2)
        if not self.subs.isChecked():
            d["subtitles"] = False
        return d

    def set_dict(self, d: dict) -> None:
        d = dict(d or {})
        k = "clip" if d.get("clip") else "find" if d.get("find") else "any"
        self.kind.setCurrentIndex([x for x, _ in KINDS].index(k))
        self.value.setText(str(d.pop("clip", None) or d.pop("find", None) or ""))
        d.pop("any", None)
        self.start.setValue(float(d.pop("start", 0) or 0))
        self.end.setValue(float(d.pop("end", 0) or 0))
        self.look.setText(str(d.pop("look", "") or ""))
        self.title.setText(str(d.pop("title", "") or "").replace("\n", " | "))
        self.duration.setValue(float(d.pop("duration", 0) or 0))
        self.subs.setChecked(bool(d.pop("subtitles", True)))
        self.extra = d


class BriefPage(QWidget):
    start_requested = Signal(Path, dict)   # збережений файл ТЗ, опції generate (out_dir, transcripts)
    open_results = Signal(Path)

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.current_path: Path | None = None   # файл, з якого відкрито / куди збережено ТЗ
        self.game: GameFolder | None = None
        self._source: Path | None = None
        self._extra_top: dict = {}
        self._yaml_dirty = False
        self._loading = False

        # --- шапка ---
        title = QLabel("MemoCut")
        title.setObjectName("h1")
        self.file_label = QLabel()
        self.file_label.setObjectName("muted")
        open_btn = QPushButton("Відкрити ТЗ…")
        open_btn.clicked.connect(self._open_file)
        self.recent_btn = QToolButton()
        self.recent_btn.setText("Нещодавні ▾")
        self.recent_btn.setPopupMode(QToolButton.InstantPopup)
        self.recent_menu = QMenu(self)
        self.recent_btn.setMenu(self.recent_menu)
        save_btn = QPushButton("Зберегти ТЗ як…")
        save_btn.clicked.connect(self._save_as)
        new_btn = QPushButton("Нове ТЗ")
        new_btn.clicked.connect(self._new)
        results_btn = QPushButton("Змонтовані раніше…")
        results_btn.setToolTip("Подивитися відео, які вже змонтовані раніше (без повторного монтажу)")
        results_btn.clicked.connect(self._pick_results)
        settings_btn = QPushButton("⚙ Налаштування")
        settings_btn.setToolTip("Підключення сервісів: ElevenLabs (озвучка)")
        settings_btn.clicked.connect(self.open_settings)
        bar = QHBoxLayout()
        for w in (open_btn, self.recent_btn, save_btn, new_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(results_btn)
        bar.addWidget(settings_btn)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_form(), "ТЗ")
        self.tabs.addTab(self._build_yaml(), "Файл ТЗ (YAML)")
        self.tabs.currentChanged.connect(self._tab_changed)
        self._prev_tab = 0

        self.err = QLabel()
        self.err.setObjectName("error")
        self.err.setWordWrap(True)
        self.go = QPushButton("Змонтувати  ▶")
        self.go.setObjectName("primary")
        self.go.setMinimumWidth(180)
        self.go.clicked.connect(self._start)
        bottom = QHBoxLayout()
        bottom.addWidget(self.err, 1)
        bottom.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        head = QHBoxLayout()
        head.addWidget(title)
        head.addSpacing(12)
        head.addWidget(self.file_label, 1, Qt.AlignBottom)
        lay.addLayout(head)
        lay.addLayout(bar)
        lay.addWidget(self.tabs, 1)
        lay.addLayout(bottom)

        self._fill_recent()
        draft = self.settings.value("draft_yaml", "")
        loaded = False
        if draft:
            try:
                import yaml
                self.set_form_data(yaml.safe_load(draft) or {})
                p = self.settings.value("draft_path", "")
                self._set_current(Path(p) if p and Path(p).is_file() else None)
                loaded = True
            except Exception:
                pass
        if not loaded:
            self._new()

    # ================= форма =================
    def _build_form(self) -> QWidget:
        body = QWidget()
        body.setObjectName("formBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(4, 10, 10, 10)
        col.setSpacing(12)

        # 1. Звідки брати відео
        c, l = _card("1. Звідки брати відео",
                     "Виберіть папку гри (наприклад «02. Між Нами про любов»). Якщо в ній є КАТАЛОГ і "
                     "«_для монтажу», програма сама візьме готові транскрипти й проксі.")
        row = QHBoxLayout()
        self.src_edit = QLineEdit()
        self.src_edit.setReadOnly(True)
        self.src_edit.setPlaceholderText("Папку ще не вибрано")
        pick = QPushButton("Вибрати папку…")
        pick.setObjectName("primary")
        pick.clicked.connect(self._pick_source)
        row.addWidget(self.src_edit, 1)
        row.addWidget(pick)
        l.addLayout(row)
        self.src_info = QLabel()
        self.src_info.setWordWrap(True)
        l.addWidget(self.src_info)
        self.folders_box = QWidget()
        self.folders_lay = QHBoxLayout(self.folders_box)
        self.folders_lay.setContentsMargins(0, 0, 0, 0)
        l.addWidget(self.folders_box)
        self.folder_checks: list[QCheckBox] = []
        col.addWidget(c)

        # 2. Ролик
        c, l = _card("2. Ролик")
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Напр. «Між нами — промо 1»")
        self.fmt = QComboBox()
        for k, label in FORMATS:
            self.fmt.addItem(label, k)
        self.style_box = QComboBox()
        self.style_box.addItems(list_styles())
        self.variations = QSpinBox()
        self.variations.setRange(1, 6)
        self.variations.setValue(3)
        self.variations.setToolTip("Скільки різних варіантів змонтувати з тих самих матеріалів")
        form.addRow("Назва:", self.name)
        form.addRow("Формат:", self.fmt)
        form.addRow("Стиль текстів:", self.style_box)
        form.addRow("Варіантів:", self.variations)
        l.addLayout(form)
        col.addWidget(c)

        # 3. Сцени
        c, l = _card("3. Сцени (по порядку)",
                     "Перша сцена — хук. «Що в кадрі» — опис для пошуку потрібного відео (на екран не виводиться). "
                     "«Напис» — текст, який буде на відео; два рядки — через « | ».")
        self.scenes_lay = QVBoxLayout()
        self.scenes_lay.setSpacing(6)
        l.addLayout(self.scenes_lay)
        add = QPushButton("+ Додати сцену")
        add.clicked.connect(lambda: self._add_scene({"any": True}))
        ar = QHBoxLayout()
        ar.addWidget(add)
        ar.addStretch()
        l.addLayout(ar)
        self.scenes: list[SceneRow] = []
        col.addWidget(c)

        # 4. Тексти поверх відео
        c, l = _card("4. Тексти поверх відео")
        form = QFormLayout()
        self.overlay = QLineEdit()
        self.overlay.setPlaceholderText("Напр. «Гра «Між нами» — 120 питань для пар» (видно весь ролик)")
        self.cta = QLineEdit()
        self.cta.setPlaceholderText("Напр. «Замовляй на memogames.ua» (окремий кадр у кінці)")
        self.whisper = QCheckBox("Розпізнавати мову для відео без готового транскрипту (довше)")
        self.whisper.setChecked(True)
        form.addRow("Упродовж відео:", self.overlay)
        form.addRow("Фінальна картка:", self.cta)
        form.addRow("Субтитри:", QLabel("з мови, караоке — вмикаються в кожній сцені окремо"))
        form.addRow("", self.whisper)
        l.addLayout(form)
        col.addWidget(c)

        # 5. Озвучка
        c, l = _card("5. Озвучка — voice-over (необов'язково)",
                     "Текст начитає голос ElevenLabs. Сцени підлаштуються під довжину озвучки, "
                     "а субтитри підуть за голосом.")
        self.vo_text = QPlainTextEdit()
        self.vo_text.setPlaceholderText("Текст для озвучки. Напр.: «Teach your kid to ask questions before they "
                                        "learn to believe everything they hear…»")
        self.vo_text.setMinimumHeight(90)
        l.addWidget(self.vo_text)
        row = QHBoxLayout()
        self.vo_voice = QComboBox()
        self.vo_voice.setMinimumWidth(260)
        self.vo_listen = QPushButton("Озвучити й прослухати")
        self.vo_listen.setToolTip("Згенерувати озвучку зараз (витрачає кредити один раз; при монтажі візьметься готова)")
        self.vo_listen.clicked.connect(self._listen)
        row.addWidget(QLabel("Голос:"))
        row.addWidget(self.vo_voice, 1)
        row.addWidget(self.vo_listen)
        l.addLayout(row)
        row = QHBoxLayout()
        self.vo_subs = QCheckBox("Субтитри з озвучки")
        self.vo_subs.setChecked(True)
        self.vo_fit = QCheckBox("Підігнати тривалість сцен під озвучку")
        self.vo_fit.setChecked(True)
        self.orig_vol = QSpinBox()
        self.orig_vol.setRange(0, 100)
        self.orig_vol.setValue(20)
        self.orig_vol.setSuffix(" %")
        self.orig_vol.setToolTip("Гучність звуку з самих відео, поки звучить озвучка")
        row.addWidget(self.vo_subs)
        row.addWidget(self.vo_fit)
        row.addStretch()
        row.addWidget(QLabel("Звук з відео:"))
        row.addWidget(self.orig_vol)
        l.addLayout(row)
        self.vo_status = QLabel()
        self.vo_status.setWordWrap(True)
        l.addWidget(self.vo_status)
        col.addWidget(c)
        self._player = None

        # 6. Музика
        c, l = _card("6. Музика (необов'язково)")
        row = QHBoxLayout()
        self.music = QLineEdit()
        self.music.setPlaceholderText("Без музики")
        self.music.setReadOnly(True)
        mpick = QPushButton("Вибрати…")
        mpick.clicked.connect(self._pick_music)
        mclear = QPushButton("Прибрати")
        mclear.clicked.connect(lambda: self.music.clear())
        self.music_vol = QSpinBox()
        self.music_vol.setRange(1, 100)
        self.music_vol.setValue(15)
        self.music_vol.setSuffix(" %")
        self.music_vol.setToolTip("Гучність музики під голосом")
        row.addWidget(self.music, 1)
        row.addWidget(mpick)
        row.addWidget(mclear)
        row.addWidget(QLabel("Гучність:"))
        row.addWidget(self.music_vol)
        l.addLayout(row)
        col.addWidget(c)

        # 7. Вільний текст
        c, l = _card("7. ТЗ від замовника (вільний текст)",
                     "Вставте сюди ТЗ як є — воно збережеться у файлі ТЗ, щоб було під рукою. "
                     "Програма його не читає: перенесіть потрібне в розділи вище.")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Наприклад: «Хук — реакція пари на питання. Субтитри обов'язково. "
                                      "Наприкінці — заклик замовити…»")
        self.notes.setMinimumHeight(110)
        l.addWidget(self.notes)
        col.addWidget(c)
        col.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        return scroll

    # ---- джерело ----
    def source_path(self) -> Path | None:
        return self._source

    def _pick_source(self) -> None:
        start = str(self._source or self.settings.value("last_source", str(Path.home())))
        d = QFileDialog.getExistingDirectory(self, "Папка гри (або папка з відео)", start)
        if d:
            self.settings.setValue("last_source", d)
            self._set_source(Path(d), None)

    def _set_source(self, path: Path | None, folders: list[str] | None) -> None:
        for cb in self.folder_checks:
            cb.setParent(None)
            cb.deleteLater()
        self.folder_checks = []
        self.game = None
        self._source = None
        if not path:
            self.src_edit.clear()
            self.src_info.setText("")
            return
        self.game = GameFolder.detect(path) if path.is_dir() else None
        self._source = self.game.root if self.game else path
        self.src_edit.setText(str(self._source))
        if not path.is_dir():
            self.src_info.setText("⚠ Папку не знайдено на цьому комп'ютері. Виберіть її заново.")
            self.src_info.setObjectName("error")
            self._restyle(self.src_info)
            return
        self.src_info.setObjectName("")
        self._restyle(self.src_info)
        if self.game:
            g = self.game
            subs = g.subfolders()
            n_tr = sum(1 for e in g.entries.values() if g.transcript(e.rel))
            self.src_info.setText(
                f"✓ Папка гри «{g.root.name}»"
                + (f" · у каталозі {len(g.entries)} файлів, готових транскриптів {n_tr}" if g.entries
                   else " · каталогу (КАТАЛОГ.csv) немає")
                + "\nБрати відео з підпапок:")
            want = set(folders) if folders else {n for n, _c, on in subs if on}
            for name, count, _on in subs:
                cb = QCheckBox(f"{name} ({count})")
                cb.setProperty("folder", name)
                cb.setChecked(name in want)
                self.folders_lay.addWidget(cb)
                self.folder_checks.append(cb)
            self.folders_lay.addStretch()
        else:
            n = len(list_videos(path))
            self.src_info.setText(f"Звичайна папка: знайдено відео {n}" + (" ⚠" if not n else ""))

    @staticmethod
    def _restyle(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    def _pick_music(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Музика", str(self._source or Path.home()),
                                           "Аудіо (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)")
        if f:
            self.music.setText(f)

    # ---- сцени ----
    def _add_scene(self, d: dict) -> SceneRow:
        r = SceneRow(self)
        r.set_dict(d)
        r.remove_requested.connect(self._remove_scene)
        r.move_requested.connect(self._move_scene)
        self.scenes.append(r)
        self.scenes_lay.addWidget(r)
        self._renumber()
        return r

    def _remove_scene(self, r: SceneRow) -> None:
        if len(self.scenes) <= 1:
            return
        self.scenes.remove(r)
        r.setParent(None)
        r.deleteLater()
        self._renumber()

    def _move_scene(self, r: SceneRow, delta: int) -> None:
        i = self.scenes.index(r)
        j = i + delta
        if 0 <= j < len(self.scenes):
            self.scenes[i], self.scenes[j] = self.scenes[j], self.scenes[i]
            self.scenes_lay.removeWidget(r)
            self.scenes_lay.insertWidget(j, r)
            self._renumber()

    def _renumber(self) -> None:
        for i, r in enumerate(self.scenes):
            r.set_number(i, len(self.scenes))

    # ---- форма <-> словник ----
    def form_data(self) -> dict:
        d = dict(self._extra_top)
        d["name"] = self.name.text().strip() or "Відео"
        if self._source:
            d["source_dir"] = str(self._source)
        if self.game:
            d["folders"] = [cb.property("folder") for cb in self.folder_checks if cb.isChecked()]
        d["format"] = self.fmt.currentData()
        d["style"] = self.style_box.currentText()
        d["variations"] = self.variations.value()
        d["segments"] = [r.to_dict() for r in self.scenes]
        for key, w in (("overlay", self.overlay), ("cta", self.cta)):
            if w.text().strip():
                d[key] = w.text().strip()
        if self.vo_text.toPlainText().strip():
            d["voiceover"] = self.vo_text.toPlainText().strip() + "\n"
            if self.vo_voice.currentData():
                d["voice"] = self.vo_voice.currentData()
            d["voice_subtitles"] = self.vo_subs.isChecked()
            d["fit_voiceover"] = self.vo_fit.isChecked()
            d["original_volume"] = round(self.orig_vol.value() / 100, 2)
        if self.music.text():
            d["music"] = self.music.text()
            d["music_volume"] = round(self.music_vol.value() / 100, 2)
        if self.notes.toPlainText().strip():
            d["notes"] = self.notes.toPlainText().strip() + "\n"
        return d

    KNOWN = {"name", "source_dir", "folders", "format", "style", "variations", "segments",
             "overlay", "cta", "music", "music_volume", "notes", "voiceover", "voice",
             "voice_subtitles", "fit_voiceover", "original_volume"}

    def set_form_data(self, d: dict) -> None:
        self._loading = True
        try:
            self._extra_top = {k: v for k, v in d.items() if k not in self.KNOWN}
            self.name.setText(str(d.get("name") or ""))
            src = d.get("source_dir")
            if src:
                p = Path(str(src))
                if not p.is_absolute() and self.current_path:
                    p = (self.current_path.parent / p).resolve()
                self._set_source(p, d.get("folders"))
            else:
                self._set_source(None, None)
            i = self.fmt.findData(str(d.get("format", "9x16")))
            self.fmt.setCurrentIndex(max(0, i))
            st = str(d.get("style", "couples_warm"))
            if self.style_box.findText(st) < 0:
                self.style_box.addItem(st)  # невідомий стиль — показати, перевірка підкаже
            self.style_box.setCurrentText(st)
            self.variations.setValue(int(d.get("variations", 3) or 3))
            for r in list(self.scenes):
                r.setParent(None)
                r.deleteLater()
            self.scenes = []
            for s in d.get("segments") or [{"any": True, "duration": 3}]:
                self._add_scene(s if isinstance(s, dict) else {"any": True})
            self.overlay.setText(str(d.get("overlay") or ""))
            self.cta.setText(str(d.get("cta") or ""))
            self.music.setText(str(d.get("music") or ""))
            self.music_vol.setValue(int(round(float(d.get("music_volume", 0.15) or 0.15) * 100)))
            self.notes.setPlainText(str(d.get("notes") or "").rstrip())
            self.vo_text.setPlainText(str(d.get("voiceover") or "").rstrip())
            self.fill_voices(str(d.get("voice") or ""))
            self.vo_subs.setChecked(bool(d.get("voice_subtitles", True)))
            self.vo_fit.setChecked(bool(d.get("fit_voiceover", True)))
            ov = d.get("original_volume")
            self.orig_vol.setValue(int(round(float(ov) * 100)) if ov is not None else 20)
        finally:
            self._loading = False

    def current_name(self) -> str:
        return self.name.text().strip() or "Відео"

    # ================= YAML =================
    def _build_yaml(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 10, 4, 4)
        hint = QLabel("Це те саме ТЗ у вигляді файлу. Збережіть його, щоб передати іншій людині або "
                      "змінити пізніше; відкрийте файл — і форма заповниться. Тут можна правити й текст: "
                      "після правок натисніть «Застосувати до форми».")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.yaml = QPlainTextEdit()
        self.yaml.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.yaml.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.yaml.textChanged.connect(self._yaml_edited)
        apply_btn = QPushButton("Застосувати до форми")
        apply_btn.clicked.connect(self._apply_yaml)
        refresh = QPushButton("Оновити з форми")
        refresh.clicked.connect(self._refresh_yaml)
        copy = QPushButton("Копіювати")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.yaml.toPlainText()))
        save = QPushButton("Зберегти файл…")
        save.clicked.connect(self._save_as)
        load = QPushButton("Відкрити файл…")
        load.clicked.connect(self._open_file)
        self.yaml_status = QLabel()
        self.yaml_status.setObjectName("muted")
        row = QHBoxLayout()
        for b in (apply_btn, refresh, copy, save, load):
            row.addWidget(b)
        row.addStretch()
        lay.addWidget(hint)
        lay.addWidget(self.yaml, 1)
        lay.addLayout(row)
        lay.addWidget(self.yaml_status)
        return w

    def yaml_text(self) -> str:
        return brief_to_yaml(self.form_data())

    def _refresh_yaml(self) -> None:
        self.yaml.blockSignals(True)
        self.yaml.setPlainText(self.yaml_text())
        self.yaml.blockSignals(False)
        self._yaml_dirty = False
        self.yaml_status.setText("Згенеровано з форми")

    def _yaml_edited(self) -> None:
        self._yaml_dirty = True
        self.yaml_status.setText("Є зміни — натисніть «Застосувати до форми»")

    def _apply_yaml(self) -> bool:
        import yaml as _yaml
        text = self.yaml.toPlainText()
        try:
            base = self.current_path.parent if self.current_path else Path.cwd()
            brief_from_text(text, base)  # перевірка: ті самі правила, що й під час монтажу
            data = _yaml.safe_load(text) or {}
        except (BriefError, _yaml.YAMLError, ValueError, TypeError) as e:
            self.yaml_status.setText(f"⚠ {e}")
            return False
        self.set_form_data(data)
        self._yaml_dirty = False
        self.yaml_status.setText("✓ Застосовано до форми")
        return True

    def _tab_changed(self, i: int) -> None:
        if i == 1:
            if not self._yaml_dirty:
                self._refresh_yaml()
        elif self._prev_tab == 1 and self._yaml_dirty:
            ans = QMessageBox.question(self, "MemoCut", "У файлі ТЗ є зміни. Застосувати їх до форми?",
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel or (ans == QMessageBox.Yes and not self._apply_yaml()):
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(1)
                self.tabs.blockSignals(False)
                return
            self._yaml_dirty = False
        self._prev_tab = self.tabs.currentIndex()

    # ================= файли =================
    def _set_current(self, p: Path | None) -> None:
        self.current_path = p
        self.file_label.setText(f"Файл ТЗ: {p}" if p else "Нове ТЗ (ще не збережене)")
        if p:
            self._remember(p)

    def _recent_list(self) -> list[str]:
        v = self.settings.value("recent_briefs", [])
        if isinstance(v, str):
            v = [v]
        out: list[str] = []
        for p in v or []:
            if Path(p).is_absolute() and Path(p).is_file() and p not in out:
                out.append(p)
        return out

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        items = self._recent_list()
        for p in items:
            act = self.recent_menu.addAction(f"{Path(p).stem}   —   {Path(p).parent}")
            act.triggered.connect(lambda _=False, p=p: self.open_path(Path(p)))
        self.recent_btn.setEnabled(bool(items))

    def _remember(self, path: Path) -> None:
        path = path.resolve()
        items = [str(path)] + [p for p in self._recent_list() if p != str(path)]
        self.settings.setValue("recent_briefs", items[:MAX_RECENT])
        self._fill_recent()

    def _new(self) -> None:
        keep_src = self._source
        self.set_form_data({"segments": [{"any": True, "duration": 3}, {"any": True, "duration": 2.5},
                                         {"any": True, "duration": 2.5}]})
        if keep_src:
            self._set_source(keep_src, None)
        self._set_current(None)
        self.err.clear()
        if self.tabs.currentIndex() == 1:
            self._refresh_yaml()

    def _open_file(self) -> None:
        start = str(self.current_path.parent if self.current_path else self.settings.value("last_dir", str(Path.home())))
        f, _ = QFileDialog.getOpenFileName(self, "Відкрити ТЗ", start, "ТЗ (*.yaml *.yml)")
        if f:
            self.open_path(Path(f))

    def open_path(self, path: Path) -> bool:
        """Відкрити файл ТЗ у форму. False — якщо файл з помилкою."""
        self.err.clear()
        try:
            data = load_brief_data(path)
        except (BriefError, OSError) as e:
            self.err.setText(f"Не вдалося відкрити {path.name}: {e}")
            return False
        self.settings.setValue("last_dir", str(path.parent))
        self.current_path = path.resolve()
        self.set_form_data(data)
        self._set_current(path.resolve())
        self._yaml_dirty = False
        if self.tabs.currentIndex() == 1:
            self._refresh_yaml()
        return True

    def _save_as(self) -> None:
        if self.tabs.currentIndex() == 1 and self._yaml_dirty and not self._apply_yaml():
            return
        base = self.current_path.parent if self.current_path else (
            project_base(self._source) / "ТЗ" if self._source else Path(self.settings.value("last_dir", str(Path.home()))))
        start = str(base / f"{safe_name(self.current_name())}.yaml")
        f, _ = QFileDialog.getSaveFileName(self, "Зберегти ТЗ", start, "ТЗ (*.yaml)")
        if f:
            p = Path(f) if f.lower().endswith((".yaml", ".yml")) else Path(f + ".yaml")
            self._write(p)

    def _write(self, p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.yaml_text(), encoding="utf-8")
        self._set_current(p.resolve())
        self.settings.setValue("last_dir", str(p.parent))

    def save_draft(self) -> None:
        """Чернетка на випадок закриття програми (відновлюється при наступному запуску)."""
        try:
            self.settings.setValue("draft_yaml", self.yaml_text())
            self.settings.setValue("draft_path", str(self.current_path or ""))
        except Exception:
            pass

    def _pick_results(self) -> None:
        start = project_base(self._source) / "Результати" if self._source else Path.home()
        if not start.is_dir():
            start = Path(self.settings.value("last_dir", str(Path.home())))
        d = QFileDialog.getExistingDirectory(self, "Папка зі змонтованими відео (де лежать var1, var2…)", str(start))
        if d:
            self.open_results.emit(Path(d))

    # ================= запуск =================
    def validate(self) -> str | None:
        """Текст помилки або None."""
        if self.tabs.currentIndex() == 1 and self._yaml_dirty and not self._apply_yaml():
            return "У файлі ТЗ помилка — див. рядок під текстом."
        if not self._source:
            return "Виберіть папку з відео (розділ 1)."
        if not self._source.is_dir():
            return f"Папку не знайдено: {self._source}"
        if self.game and not any(cb.isChecked() for cb in self.folder_checks):
            return "Позначте хоча б одну підпапку, з якої брати відео."
        for i, r in enumerate(self.scenes, 1):
            k = r.kind.currentData()
            if k != "any" and not r.value.text().strip():
                what = "фразу" if k == "find" else "ID або назву файлу"
                return f"Сцена {i}: впишіть {what} або виберіть «Найкращий кадр»."
            if k == "clip" and r.end.value() and r.end.value() <= r.start.value():
                return f"Сцена {i}: «до» має бути більше за «від»."
        if self.game:
            for i, r in enumerate(self.scenes, 1):
                v = r.value.text().strip()
                # без розширення — це ID з каталогу; перевіряємо, що він є
                if r.kind.currentData() == "clip" and v and "." not in Path(v).name \
                        and self.game.resolve_clip(v) == v:
                    return f"Сцена {i}: ID «{v}» немає в КАТАЛОГ.csv цієї гри."
        if self.vo_text.toPlainText().strip():
            cfg = tts_config(self.settings)
            if not cfg.api_key:
                return "Для озвучки потрібен API-ключ ElevenLabs: ⚙ Налаштування."
            if not (self.vo_voice.currentData() or cfg.voice_id):
                return "Виберіть голос для озвучки (розділ 5 або ⚙ Налаштування)."
        try:
            parse_brief(self.form_data(), self._source)
        except (BriefError, ValueError, TypeError) as e:
            return str(e)
        return None

    def _start(self) -> None:
        msg = self.validate()
        self.err.setText(msg or "")
        if msg:
            return
        base = project_base(self._source)
        path = self.current_path or (base / "ТЗ" / f"{safe_name(self.current_name())}.yaml")
        try:
            self._write(path)
        except OSError as e:
            self.err.setText(f"Не вдалося зберегти ТЗ у {path}: {e}")
            return
        self.save_draft()
        self.start_requested.emit(path, {"out_dir": base / "Результати",
                                         "transcripts": self.whisper.isChecked(),
                                         "tts": tts_config(self.settings)})

    # ================= озвучка / налаштування =================
    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        if SettingsDialog(self.settings, self).exec():
            self.fill_voices(self.vo_voice.currentData() or "")

    def fill_voices(self, current: str = "") -> None:
        cfg = tts_config(self.settings)
        self.vo_voice.clear()
        default = next((v["name"] for v in cached_voices(self.settings) if v["voice_id"] == cfg.voice_id), None)
        self.vo_voice.addItem(f"З Налаштувань ({default})" if default else "З Налаштувань", "")
        for v in cached_voices(self.settings):
            self.vo_voice.addItem(v["name"] + (f"  ({v['info']})" if v.get("info") else ""), v["voice_id"])
        if current:
            i = self.vo_voice.findData(current)
            if i < 0:
                self.vo_voice.addItem(f"voice_id {current}", current)
                i = self.vo_voice.count() - 1
            self.vo_voice.setCurrentIndex(i)
        self.vo_status.setText("" if cfg.api_key else
                               "Щоб озвучувати, додайте API-ключ ElevenLabs: кнопка «⚙ Налаштування» вгорі.")

    def _listen(self) -> None:
        text = self.vo_text.toPlainText().strip()
        if not text:
            self.vo_status.setText("Впишіть текст озвучки.")
            return
        if not self._source:
            self.vo_status.setText("Спершу виберіть папку гри (розділ 1) — туди збережеться озвучка.")
            return
        from .workers import Job, start_job
        cfg = tts_config(self.settings)
        self.vo_listen.setEnabled(False)
        self.vo_status.setText("Озвучую…")
        job = Job(_synth_job, text, cfg, project_base(self._source) / "озвучка", self.vo_voice.currentData() or None)
        job.finished.connect(self._listen_ok)
        job.failed.connect(self._listen_fail)
        self._vo_job = job
        start_job(self, job)

    def _listen_ok(self, res) -> None:
        mp3, dur = res
        self.vo_listen.setEnabled(True)
        self.vo_status.setText(f"✓ Озвучка {dur:.1f} с. Відео буде приблизно такої ж довжини."
                               f"  Файл: {mp3.name}")
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(mp3)))
        self._player.play()

    def _listen_fail(self, msg: str, _tb: str) -> None:
        self.vo_listen.setEnabled(True)
        self.vo_status.setText(f"⚠ {msg}")


def _synth_job(text, cfg, out_dir, voice, progress=None):
    from ..core.project import audio_duration
    from ..core.tts import synthesize
    mp3, _words = synthesize(text, cfg, out_dir, voice)
    return mp3, audio_duration(mp3)
