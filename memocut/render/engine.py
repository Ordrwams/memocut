"""Шар 3 — рендер плану в MP4 через FFmpeg.

Кожен сегмент рендериться окремо й кешується за хешем свого вмісту
(<source_dir>/.memocut/render_cache). Після правки одного сегмента
перерендерюється тільки він, а решта склеюється з кешу (concat без перекодування).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from ..core import paths
from ..core.models import Catalog, Plan, Segment, Word
from ..core.tts import VO_DELAY
from ..core.proc import run
from ..core.style import load_style
from . import ass

SIZES = {"9x16": (1080, 1920), "1x1": (1080, 1080), "16x9": (1920, 1080), "4x5": (1080, 1350)}

Progress = Callable[[str, float], None]


def out_size(fmt: str, preview: bool) -> tuple[int, int]:
    w, h = SIZES[fmt]
    return (w // 2, h // 2) if preview else (w, h)


def _enc(preview: bool) -> list[str]:
    if preview:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high"]


_AENC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


class Renderer:
    def __init__(self, catalog: Catalog, progress: Optional[Progress] = None):
        self.catalog = catalog
        self.source = Path(catalog.source_dir)
        self.cache = self.source / ".memocut" / "render_cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        fonts = self.cache / "fonts"
        if not fonts.exists():
            shutil.copytree(paths.fonts_dir(), fonts)
        self.say = progress or (lambda m, f: None)

    # ---- один сегмент ----
    def _key(self, seg: Segment, style: dict, fmt: str, preview: bool, overlay: str | None = None,
             vo_words: list | None = None) -> str:
        clip = self.catalog.get(seg.shot.file)
        payload = {
            "shot": asdict(seg.shot) | {"score": 0, "reason": ""}, "title": seg.title, "sub": seg.subtitles,
            "style": style, "fmt": fmt, "preview": preview, "overlay": overlay, "vo": [asdict(w) for w in vo_words] if vo_words is not None else None,
            "clip": [clip.mtime, clip.size, [asdict(w) for w in clip.words
                                             if seg.shot.start - 1 < w.s < seg.shot.end + 1]] if clip else None,
            "v": 5,
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    def render_segment(self, seg: Segment, style: dict, fmt: str, preview: bool,
                       overlay: str | None = None, vo_words: list | None = None) -> Path:
        key = self._key(seg, style, fmt, preview, overlay, vo_words)
        out = self.cache / f"seg_{key}.mp4"
        if out.exists():
            return out
        clip = self.catalog.get(seg.shot.file)
        if clip is None:
            raise FileNotFoundError(f"Кліп {seg.shot.file} відсутній у каталозі")
        w, h = out_size(fmt, preview)
        fw, fh = SIZES[fmt]
        ass_name = f"seg_{key}.ass"
        (self.cache / ass_name).write_text(ass.segment_ass(seg, clip, style, fw, fh, overlay, vo_words), encoding="utf-8")
        dur = seg.shot.duration
        fps = style["video"]["fps"]
        vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
              f"fps={fps},format=yuv420p,subtitles={ass_name}:fontsdir=fonts[v]")
        args = [paths.ffmpeg(), "-y", "-v", "error", "-ss", f"{seg.shot.start:.3f}", "-t", f"{dur:.3f}",
                "-i", str(self.source / seg.shot.file)]
        if clip.has_audio:
            af = "[0:a]"
        else:
            args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            af = "[1:a]"
        fade_out = max(0.0, dur - 0.05)
        fc = (vf + f";{af}aresample=48000,aformat=channel_layouts=stereo,"
              f"afade=t=in:d=0.03,afade=t=out:st={fade_out:.3f}:d=0.05,apad[a]")
        tmp = self.cache / f"tmp_{key}.mp4"
        run(args + ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
                    *_enc(preview), *_AENC, "-movflags", "+faststart", tmp.name], cwd=str(self.cache))
        tmp.replace(out)
        return out

    def render_end_card(self, text: str, style: dict, fmt: str, preview: bool) -> Path:
        ec = style["end_card"]
        key = hashlib.sha1(json.dumps([text, style, fmt, preview, 3], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()[:16]
        out = self.cache / f"end_{key}.mp4"
        if out.exists():
            return out
        w, h = out_size(fmt, preview)
        fw, fh = SIZES[fmt]
        dur = float(ec["duration"])
        ass_name = f"end_{key}.ass"
        (self.cache / ass_name).write_text(ass.end_card_ass(text, style, fw, fh, dur), encoding="utf-8")
        bg = ec["background"].replace("#", "0x")
        tmp = self.cache / f"tmp_{key}.mp4"
        run([paths.ffmpeg(), "-y", "-v", "error",
             "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}:d={dur}:r={style['video']['fps']}",
             "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo",
             "-vf", f"format=yuv420p,subtitles={ass_name}:fontsdir=fonts",
             *_enc(preview), *_AENC, "-t", f"{dur}", "-movflags", "+faststart", tmp.name], cwd=str(self.cache))
        tmp.replace(out)
        return out

    # ---- увесь план ----
    def render(self, plan: Plan, out_path: Path, preview: bool = False) -> Path:
        style = load_style(plan.style)
        parts = []
        n = len(plan.segments) + (1 if plan.cta else 0)
        t = 0.0
        vo_subs = bool(plan.voiceover and plan.voice_subtitles and plan.voiceover_words)
        for i, seg in enumerate(plan.segments):
            self.say(f"Сегмент {i + 1}/{len(plan.segments)}", i / (n + 1))
            vo = None
            if vo_subs:  # слова озвучки, що звучать під час цього сегмента, у його власному часі
                d = seg.shot.duration
                vo = [Word(w.w, round(w.s + VO_DELAY - t, 3), round(w.e + VO_DELAY - t, 3))
                      for w in plan.voiceover_words if w.e + VO_DELAY > t + 0.05 and w.s + VO_DELAY < t + d - 0.05]
            parts.append(self.render_segment(seg, style, plan.format, preview, plan.overlay, vo))
            t += seg.shot.duration
        if plan.cta:
            self.say("Фінальна картка", len(plan.segments) / (n + 1))
            parts.append(self.render_end_card(plan.cta, style, plan.format, preview))

        self.say("Склейка", n / (n + 1))
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lst = self.cache / f"list_{out_path.stem}_{id(plan)}.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        joined = self.cache / f"joined_{id(plan)}.mp4"
        run([paths.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
             "-c", "copy", "-movflags", "+faststart", joined.name], cwd=str(self.cache))
        lst.unlink(missing_ok=True)

        music = self._music_path(plan)
        voice = self._voice_path(plan)
        if music or voice or abs(plan.original_volume - 1.0) > 1e-3:
            # Зведення: звук з відео (приглушений під озвучку) + озвучка + музика.
            total = plan.duration + (style["end_card"]["duration"] if plan.cta else 0)
            args = [paths.ffmpeg(), "-y", "-v", "error", "-i", str(joined)]
            fc = [f"[0:a]volume={plan.original_volume:.3f}[o]"]
            mix = ["[o]"]
            if voice:
                args += ["-i", str(voice)]
                ms = int(VO_DELAY * 1000)
                fc.append(f"[{sum(1 for a in args if a == '-i') - 1}:a]aresample=48000,aformat=channel_layouts=stereo,"
                          f"volume={plan.voice_volume:.3f},adelay={ms}|{ms}[vo]")
                mix.append("[vo]")
            if music:
                args += ["-stream_loop", "-1", "-i", str(music)]
                idx = sum(1 for a in args if a == "-i") - 1
                fc.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={plan.music_volume},"
                          f"afade=t=in:d=0.5,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[m]")
                mix.append("[m]")
            fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0[a]")
            run(args + ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-c:v", "copy", *_AENC,
                        "-movflags", "+faststart", str(out_path)])
            joined.unlink(missing_ok=True)
        else:
            shutil.move(str(joined), str(out_path))
        self.say("Готово", 1.0)
        return out_path

    def _voice_path(self, plan: Plan) -> Optional[Path]:
        if not plan.voiceover:
            return None
        p = Path(plan.voiceover)
        if not p.is_file():
            raise FileNotFoundError(f"Файл озвучки не знайдено: {p}. Змонтуйте ТЗ заново, щоб озвучити ще раз.")
        return p

    def _music_path(self, plan: Plan) -> Optional[Path]:
        if not plan.music:
            return None
        p = Path(plan.music)
        for cand in (p, self.source / p, paths.exe_dir() / "music" / p):
            if cand.is_file():
                return cand
        raise FileNotFoundError(f"Музику не знайдено: {plan.music}")

    def clear_cache(self) -> None:
        for p in self.cache.glob("*.mp4"):
            p.unlink()
        for p in self.cache.glob("*.ass"):
            p.unlink()
