"""Шар 1 — аналіз папки з сирими відео.

Для кожного кліпу: тривалість, склейки (сцени), паузи, яскравість по секундах,
прев'ю-кадр і транскрипт по словах. Результат кешується в
<source_dir>/.memocut/catalog.json і перераховується тільки для змінених файлів.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from ..core import paths
from ..core.models import Catalog, ClipInfo, Word
from ..core.proc import FFmpegError, run
from ..core.library import GameFolder, skip_dir
from . import transcribe

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts"}
CACHE_DIRNAME = ".memocut"

Progress = Callable[[str, float], None]  # (повідомлення, частка 0..1)


def cache_dir(source: Path) -> Path:
    d = source / CACHE_DIRNAME
    d.mkdir(exist_ok=True)
    return d


def probe(path: Path) -> dict:
    p = run([paths.ffprobe(), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    data = json.loads(p.stdout)
    v = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if v is None:
        raise ValueError("немає відеодоріжки")
    a = any(s.get("codec_type") == "audio" for s in data["streams"])
    num, _, den = (v.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) % 180 == 90:  # телефонне відео з поворотом
        w, h = h, w
    return {
        "duration": float(data["format"].get("duration") or v.get("duration") or 0),
        "width": w, "height": h, "fps": round(fps, 3), "has_audio": a,
    }


_PTS = re.compile(r"pts_time:([\d.]+)")
_KV = re.compile(r"(lavfi\.[\w.]+)=([-\d.]+)")
_SIL_S = re.compile(r"silence_start: ([-\d.]+)")
_SIL_E = re.compile(r"silence_end: ([-\d.]+)")


def detect(path: Path, has_audio: bool, duration: float,
           scene_threshold: float = 0.32) -> tuple[list[float], list[list[float]], list[float]]:
    """Один прохід ffmpeg: склейки + яскравість (1/сек) + тиша."""
    fc = ("[0:v]scale=192:-2,split=2[a][b];"
          # eq(n,0): перший кадр проходить завжди — інакше у відео без склейок цей вихід порожній,
          # і нові ffmpeg падають з «Could not open encoder before EOF». Поріг перевіряємо нижче.
          f"[a]select='eq(n\\,0)+gt(scene\\,{scene_threshold})',metadata=print:key=lavfi.scene_score[sa];"
          "[b]fps=1,signalstats,metadata=print:key=lavfi.signalstats.YAVG[sb]")
    args = [paths.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-filter_complex"]
    if has_audio:
        fc += ";[0:a]silencedetect=n=-35dB:d=0.45[aa]"
        args += [fc, "-map", "[sa]", "-f", "null", "-", "-map", "[sb]", "-f", "null", "-",
                 "-map", "[aa]", "-f", "null", "-"]
    else:
        args += [fc, "-map", "[sa]", "-f", "null", "-", "-map", "[sb]", "-f", "null", "-"]
    p = run(args, check=False)
    err = p.stderr
    if p.returncode != 0 and "lavfi.signalstats.YAVG" not in err:
        tail = "\n".join(err.strip().splitlines()[-8:])
        raise FFmpegError(f"Не вдалося проаналізувати відео:\n{tail}")

    scenes, bright, silences = [], [], []
    last_t = None
    sil_start = None
    for line in err.splitlines():
        m = _PTS.search(line)
        if m:
            last_t = float(m.group(1))
            continue
        m = _KV.search(line)
        if m and last_t is not None:
            if m.group(1) == "lavfi.scene_score":
                if float(m.group(2)) > scene_threshold and last_t > 0:
                    scenes.append(round(last_t, 3))
            elif m.group(1) == "lavfi.signalstats.YAVG":
                bright.append(round(float(m.group(2)), 1))
            continue
        m = _SIL_S.search(line)
        if m:
            sil_start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_E.search(line)
        if m and sil_start is not None:
            silences.append([round(sil_start, 3), round(float(m.group(1)), 3)])
            sil_start = None
    if sil_start is not None:
        silences.append([round(sil_start, 3), round(duration, 3)])
    return sorted(set(scenes)), silences, bright


def make_thumb(path: Path, out: Path, at: float) -> None:
    run([paths.ffmpeg(), "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", str(out)])


def list_videos(source: Path, folders: Optional[list[str]] = None, game: Optional[GameFolder] = None) -> list[Path]:
    """Усі відео в source. folders — лише ці підпапки; у папці гри службові/«з текстом» пропускаються."""
    roots = [source / f for f in folders] if folders else [source]
    out = []
    for r in roots:
        if not r.is_dir():
            continue
        for p in r.rglob("*"):
            if p.suffix.lower() not in VIDEO_EXT or CACHE_DIRNAME in p.parts:
                continue
            if game is not None and any(skip_dir(x) for x in p.relative_to(source).parts[:-1]):
                continue
            out.append(p)
    return sorted(set(out))


def analyze(source: str | Path, *, transcripts: bool = True, folders: Optional[list[str]] = None,
            progress: Optional[Progress] = None) -> Catalog:
    """folders — підпапки source, з яких брати відео (None = усі)."""
    source = Path(source).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Папка не знайдена: {source}")
    game = GameFolder.detect(source)

    def grel(f: Path) -> str:  # шлях від кореня гри (як у КАТАЛОГ.csv)
        return f.relative_to(game.root).as_posix() if game else ""
    cdir = cache_dir(source)
    cat_path = cdir / "catalog.json"
    old = Catalog.load(cat_path) if cat_path.exists() else Catalog(str(source))
    thumbs = cdir / "thumbs"
    thumbs.mkdir(exist_ok=True)

    files = list_videos(source, folders, game)
    clips: list[ClipInfo] = []
    say = progress or (lambda m, f: None)
    for i, f in enumerate(files):
        rel = f.relative_to(source).as_posix()
        st = f.stat()
        prev = old.get(rel)
        if prev and prev.mtime == st.st_mtime and prev.size == st.st_size and (prev.words or not transcripts or not info_has_audio(prev)):
            prev.desc = (game.entries[grel(f)].desc if game and grel(f) in game.entries else "")
            clips.append(prev)
            continue
        say(f"Аналіз {rel}", i / max(1, len(files)))
        try:
            info = probe(f)
        except Exception as e:  # битий файл не має зупиняти весь аналіз
            say(f"Пропущено {rel}: {e}", i / max(1, len(files)))
            continue
        if prev and prev.mtime == st.st_mtime and prev.size == st.st_size:
            clip = prev  # бракує лише транскрипту
        else:
            # Проксі 480p з папки гри має ті самі таймкоди, але аналізується в рази швидше.
            src = (game.proxy(grel(f)) if game else None) or f
            try:
                scenes, silences, bright = detect(src, info["has_audio"], info["duration"])
            except Exception as e:  # один проблемний файл не зупиняє монтаж: беремо без аналізу сцен
                if src != f:
                    try:
                        scenes, silences, bright = detect(f, info["has_audio"], info["duration"])
                    except Exception:
                        scenes, silences, bright = [], [], []
                else:
                    scenes, silences, bright = [], [], []
                if not bright:
                    say(f"Увага: {rel} — не вдалося проаналізувати ({str(e).splitlines()[0]})",
                        i / max(1, len(files)))
            thumb = thumbs / (re.sub(r"[^\w.-]", "_", rel) + ".jpg")
            make_thumb(src, thumb, min(1.0, info["duration"] / 2))
            clip = ClipInfo(file=rel, mtime=st.st_mtime, size=st.st_size, scenes=scenes,
                            silences=silences, brightness=bright,
                            thumb=thumb.relative_to(source).as_posix(), **info)
        if info["has_audio"] and not clip.words:
            say(f"Транскрипт {rel}", (i + 0.5) / max(1, len(files)))
            clip.words = [Word(**w) for w in transcribe.words_for(
                f, whisper=transcripts,
                timed_txt=game.transcript(grel(f)) if game else None,
                known_empty=game.has_transcript_file(grel(f)) if game else False)]
        clip.desc = (game.entries[grel(f)].desc if game and grel(f) in game.entries else "")
        clips.append(clip)
        Catalog(str(source), clips + [c for c in old.clips if c.file not in {x.file for x in clips}]).save(cat_path)

    cat = Catalog(str(source), clips)
    cat.save(cat_path)
    say("Аналіз завершено", 1.0)
    return cat


def info_has_audio(c: ClipInfo) -> bool:
    return c.has_audio


def load_or_analyze(source: str | Path, **kw) -> Catalog:
    return analyze(source, **kw)
