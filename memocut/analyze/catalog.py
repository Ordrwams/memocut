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
from ..core.proc import run
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
          f"[a]select='gt(scene,{scene_threshold})',metadata=print:key=lavfi.scene_score[sa];"
          "[b]fps=1,signalstats,metadata=print:key=lavfi.signalstats.YAVG[sb]")
    args = [paths.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-filter_complex"]
    if has_audio:
        fc += ";[0:a]silencedetect=n=-35dB:d=0.45[aa]"
        args += [fc, "-map", "[sa]", "-f", "null", "-", "-map", "[sb]", "-f", "null", "-",
                 "-map", "[aa]", "-f", "null", "-"]
    else:
        args += [fc, "-map", "[sa]", "-f", "null", "-", "-map", "[sb]", "-f", "null", "-"]
    err = run(args).stderr

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


def list_videos(source: Path) -> list[Path]:
    return sorted(p for p in source.rglob("*")
                  if p.suffix.lower() in VIDEO_EXT and CACHE_DIRNAME not in p.parts)


def analyze(source: str | Path, *, transcripts: bool = True,
            progress: Optional[Progress] = None) -> Catalog:
    source = Path(source).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Папка не знайдена: {source}")
    cdir = cache_dir(source)
    cat_path = cdir / "catalog.json"
    old = Catalog.load(cat_path) if cat_path.exists() else Catalog(str(source))
    thumbs = cdir / "thumbs"
    thumbs.mkdir(exist_ok=True)

    files = list_videos(source)
    clips: list[ClipInfo] = []
    say = progress or (lambda m, f: None)
    for i, f in enumerate(files):
        rel = f.relative_to(source).as_posix()
        st = f.stat()
        prev = old.get(rel)
        if prev and prev.mtime == st.st_mtime and prev.size == st.st_size and (prev.words or not transcripts or not info_has_audio(prev)):
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
            scenes, silences, bright = detect(f, info["has_audio"], info["duration"])
            thumb = thumbs / (re.sub(r"[^\w.-]", "_", rel) + ".jpg")
            make_thumb(f, thumb, min(1.0, info["duration"] / 2))
            clip = ClipInfo(file=rel, mtime=st.st_mtime, size=st.st_size, scenes=scenes,
                            silences=silences, brightness=bright,
                            thumb=thumb.relative_to(source).as_posix(), **info)
        if info["has_audio"] and not clip.words:
            say(f"Транскрипт {rel}", (i + 0.5) / max(1, len(files)))
            clip.words = [Word(**w) for w in transcribe.words_for(f, whisper=transcripts)]
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
