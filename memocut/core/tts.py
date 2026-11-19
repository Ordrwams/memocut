"""Озвучка (voice-over) через ElevenLabs — єдина частина MemoCut, що ходить в інтернет, і лише коли в ТЗ є текст озвучки.

API-ключ НЕ зберігається в ТЗ (ТЗ передають іншим людям): GUI бере його з Налаштувань,
CLI — зі змінної середовища ELEVENLABS_API_KEY.

Кожен згенерований файл кешується за (текст, голос, модель): повторний монтаж/правки кредити не витрачають.
Разом з mp3 зберігаються таймкоди слів (endpoint with-timestamps) — з них робляться субтитри озвучки.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

API = os.environ.get("MEMOCUT_ELEVENLABS_URL", "https://api.elevenlabs.io")
MODELS = [
    ("eleven_multilingual_v2", "Multilingual v2 — найкраща якість, 29 мов"),
    ("eleven_v3", "v3 — найвиразніша (емоції)"),
    ("eleven_flash_v2_5", "Flash v2.5 — швидка й дешевша"),
]
DEFAULT_MODEL = MODELS[0][0]
VO_DELAY = 0.2      # озвучка починається через 0.2 с після старту відео
VO_TAIL = 0.5       # і відео триває ще 0.5 с після неї


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    voice_id: str = ""          # голос за замовчуванням

    @staticmethod
    def from_env() -> "TTSConfig":
        return TTSConfig(api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
                         model=os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL),
                         voice_id=os.environ.get("ELEVENLABS_VOICE", ""))


def _request(path: str, api_key: str, body: Optional[dict] = None, timeout: float = 120) -> dict:
    if not api_key:
        raise TTSError("Не вказано API-ключ ElevenLabs (Налаштування → ElevenLabs).")
    req = urllib.request.Request(
        API + path, method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
            msg = detail.get("message") if isinstance(detail, dict) else detail
            status = (detail.get("status") or "") if isinstance(detail, dict) else ""
        except Exception:
            msg = None
        if "permission" in f"{status} {msg}".lower():
            need = "Voices → Read" if "voices" in path else "Text to Speech → Access"
            raise TTSError("Ключу ElevenLabs бракує дозволу. На elevenlabs.io → API Keys → цей ключ → "
                           f"увімкніть «{need}» і збережіть.\n(Відповідь ElevenLabs: {msg})") from None
        if e.code == 401:
            raise TTSError("ElevenLabs не прийняв API-ключ. Перевірте його в Налаштуваннях.") from None
        if e.code == 402 or (msg and "quota" in str(msg).lower()):
            raise TTSError(f"ElevenLabs: закінчились кредити або тариф не дозволяє. {msg or ''}") from None
        raise TTSError(f"ElevenLabs відповів помилкою {e.code}: {msg or e.reason}") from None
    except urllib.error.URLError as e:
        raise TTSError(f"Немає зв'язку з ElevenLabs: {e.reason}. Перевірте інтернет.") from None


def list_voices(api_key: str) -> list[dict]:
    """[{voice_id, name, info}] — голоси акаунта (свої + додані з бібліотеки)."""
    data = _request("/v1/voices", api_key, timeout=30)
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels") or {}
        info = ", ".join(str(x) for x in (labels.get("gender"), labels.get("accent"), labels.get("age"),
                                          labels.get("description") or labels.get("descriptive")) if x)
        out.append({"voice_id": v["voice_id"], "name": v.get("name", v["voice_id"]), "info": info})
    return sorted(out, key=lambda x: x["name"].lower())


def chars_to_words(alignment: dict) -> list[dict]:
    """Посимвольні таймкоди ElevenLabs -> слова [{w, s, e}]."""
    chars = alignment.get("characters") or []
    st = alignment.get("character_start_times_seconds") or []
    en = alignment.get("character_end_times_seconds") or []
    words, cur, s0, e0 = [], "", None, None
    for ch, a, b in zip(chars, st, en):
        if ch.isspace():
            if cur:
                words.append({"w": cur, "s": round(s0, 3), "e": round(e0, 3)})
            cur, s0 = "", None
            continue
        if s0 is None:
            s0 = a
        cur += ch
        e0 = b
    if cur:
        words.append({"w": cur, "s": round(s0, 3), "e": round(e0, 3)})
    return words


def cache_key(text: str, voice_id: str, model: str) -> str:
    return hashlib.sha1(json.dumps([text.strip(), voice_id, model], ensure_ascii=False).encode()).hexdigest()[:16]


def synthesize(text: str, cfg: TTSConfig, out_dir: Path, voice_id: str | None = None) -> tuple[Path, list[dict]]:
    """Озвучити текст. Повертає (mp3, слова з таймкодами). Повторний виклик з тим самим текстом — з кешу."""
    text = text.strip()
    if not text:
        raise TTSError("Текст озвучки порожній.")
    voice = voice_id or cfg.voice_id
    if not voice:
        raise TTSError("Не вибрано голос для озвучки (Налаштування → ElevenLabs або розділ «Озвучка»).")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key(text, voice, cfg.model)
    mp3, wj = out_dir / f"vo_{key}.mp3", out_dir / f"vo_{key}.words.json"
    if mp3.is_file() and wj.is_file():
        return mp3, json.loads(wj.read_text(encoding="utf-8"))
    body = {"text": text, "model_id": cfg.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    data = _request(f"/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128",
                    cfg.api_key, body, timeout=300)
    audio = data.get("audio_base64")
    if not audio:
        raise TTSError("ElevenLabs не повернув аудіо.")
    words = chars_to_words(data.get("alignment") or data.get("normalized_alignment") or {})
    tmp = mp3.with_suffix(".tmp")
    tmp.write_bytes(base64.b64decode(audio))
    tmp.replace(mp3)
    wj.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"vo_{key}.txt").write_text(text, encoding="utf-8")  # щоб було видно, що озвучено
    return mp3, words
