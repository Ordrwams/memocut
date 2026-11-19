"""Налаштування: підключення зовнішніх сервісів (зараз — ElevenLabs для озвучки).

Ключі зберігаються лише на цьому комп'ютері (QSettings), у файл ТЗ не потрапляють.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from ..core import tts
from .workers import Job, start_job

K_KEY, K_MODEL, K_VOICE, K_VOICES = ("elevenlabs/api_key", "elevenlabs/model",
                                     "elevenlabs/voice_id", "elevenlabs/voices")


def tts_config(settings: QSettings) -> tts.TTSConfig:
    return tts.TTSConfig(api_key=str(settings.value(K_KEY, "") or ""),
                         model=str(settings.value(K_MODEL, tts.DEFAULT_MODEL) or tts.DEFAULT_MODEL),
                         voice_id=str(settings.value(K_VOICE, "") or ""))


def cached_voices(settings: QSettings) -> list[dict]:
    try:
        return json.loads(settings.value(K_VOICES, "[]") or "[]")
    except (TypeError, ValueError):
        return []


def _voices_job(api_key: str, progress=None):
    return tts.list_voices(api_key)


class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Налаштування — MemoCut")
        self.setMinimumWidth(620)
        self.job: Job | None = None

        head = QLabel("ElevenLabs — озвучка (voice-over)")
        head.setObjectName("h2")
        hint = QLabel("Ключ: elevenlabs.io → профіль (ліворуч унизу) → <b>API Keys</b> → Create API Key. "
                      "Якщо ключ обмежений (Restrict Key), увімкніть <b>Text to Speech → Access</b> і "
                      "<b>Voices → Read</b>. "
                      "Ключ зберігається лише на цьому комп'ютері й не потрапляє у файл ТЗ. "
                      "Озвучка витрачає кредити ElevenLabs; той самий текст повторно не озвучується (кеш).")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)

        self.key = QLineEdit(str(settings.value(K_KEY, "") or ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk_…")
        show = QCheckBox("показати")
        show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        krow = QHBoxLayout()
        krow.addWidget(self.key, 1)
        krow.addWidget(show)

        self.model = QComboBox()
        for mid, label in tts.MODELS:
            self.model.addItem(label, mid)
        cur = str(settings.value(K_MODEL, tts.DEFAULT_MODEL))
        i = self.model.findData(cur)
        if i < 0:
            self.model.addItem(cur, cur)
            i = self.model.count() - 1
        self.model.setCurrentIndex(i)

        self.voice = QComboBox()
        self.check = QPushButton("Перевірити ключ і завантажити голоси")
        self.check.clicked.connect(self._load_voices)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self._fill_voices(cached_voices(settings), str(settings.value(K_VOICE, "") or ""))

        form = QFormLayout()
        form.addRow("API-ключ:", krow)
        form.addRow("Модель:", self.model)
        form.addRow("Голос за замовчуванням:", self.voice)
        form.addRow("", self.check)
        form.addRow("", self.status)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        more = QLabel("Інші сервіси (напр. Claude для розумного підбору сцен) з'являться тут пізніше.")
        more.setObjectName("muted")

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("Зберегти")
        btns.button(QDialogButtonBox.Cancel).setText("Скасувати")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(line)
        lay.addWidget(more)
        lay.addWidget(btns)

    def _fill_voices(self, voices: list[dict], current: str) -> None:
        self.voice.clear()
        if not voices:
            self.voice.addItem("— спершу «Перевірити ключ…» —", "")
        for v in voices:
            self.voice.addItem(f"{v['name']}" + (f"  ({v['info']})" if v.get("info") else ""), v["voice_id"])
        i = self.voice.findData(current)
        if i >= 0:
            self.voice.setCurrentIndex(i)
        elif current:
            self.voice.addItem(f"voice_id {current}", current)
            self.voice.setCurrentIndex(self.voice.count() - 1)

    def _load_voices(self) -> None:
        if self.job:
            return
        self.check.setEnabled(False)
        self.status.setText("Перевіряю…")
        job = Job(_voices_job, self.key.text().strip())
        job.finished.connect(self._voices_ok)
        job.failed.connect(self._voices_fail)
        self.job = job
        start_job(self, job)

    def _voices_ok(self, voices: list) -> None:
        self.job = None
        self.check.setEnabled(True)
        self.settings.setValue(K_VOICES, json.dumps(voices, ensure_ascii=False))
        self._fill_voices(voices, self.voice.currentData() or str(self.settings.value(K_VOICE, "") or ""))
        self.status.setText(f"✓ Ключ працює. Голосів в акаунті: {len(voices)}.")

    def _voices_fail(self, msg: str, _tb: str) -> None:
        self.job = None
        self.check.setEnabled(True)
        self.status.setText(f"⚠ {msg}")

    def _save(self) -> None:
        self.settings.setValue(K_KEY, self.key.text().strip())
        self.settings.setValue(K_MODEL, self.model.currentData())
        self.settings.setValue(K_VOICE, self.voice.currentData() or "")
        self.accept()
