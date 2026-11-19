"""Шар 2 — планувальник за правилами (без ШІ).

Для кожного слоту ТЗ будує список кандидатів (Shot) з оцінкою, далі
кожна варіація бере інший найкращий кандидат. Решта кандидатів зберігається
в Segment.alternatives — саме їх показує редактор у панелі «Альтернативи».
"""
from __future__ import annotations

import fnmatch
import re
from typing import Iterable

from ..core.brief import Brief, Slot
from ..core.models import Catalog, ClipInfo, Plan, Segment, Shot

DEFAULT_ANY = 3.0      # тривалість «будь-якого» шматка, сек
MIN_SHOT = 0.8
PAD_BEFORE = 0.25
PAD_AFTER = 0.35
MAX_ALTS = 8

_TOKEN = re.compile(r"[\w'’ʼ-]+", re.UNICODE)


def norm_tokens(text: str) -> list[str]:
    return [t.lower().replace("’", "'").replace("ʼ", "'") for t in _TOKEN.findall(text)]


def stem_eq(a: str, b: str) -> bool:
    """Грубе порівняння з урахуванням закінчень: «сміялися» ~ «сміялись»."""
    if a == b:
        return True
    n = max(3, min(len(a), len(b)) - 2)
    return len(a) >= 3 and len(b) >= 3 and a[:n] == b[:n]


# ---------- допоміжне по кліпу ----------

def _brightness_score(clip: ClipInfo, s: float, e: float) -> float:
    vals = clip.brightness[int(s):max(int(s) + 1, int(e))]
    if not vals:
        return 0.5
    avg = sum(vals) / len(vals)
    if avg < 35:
        return 0.1
    if avg > 230:
        return 0.3
    return 1.0 - abs(avg - 120) / 200


def _silence_ratio(clip: ClipInfo, s: float, e: float) -> float:
    if e <= s:
        return 1.0
    tot = sum(max(0.0, min(e, b) - max(s, a)) for a, b in clip.silences)
    return tot / (e - s)


def _snap_words(clip: ClipInfo, s: float, e: float) -> tuple[float, float]:
    """Не різати посеред слова."""
    for w in clip.words:
        if w.s < s < w.e:
            s = w.s - 0.05
        if w.s < e < w.e:
            e = w.e + 0.05
    return max(0.0, s), min(clip.duration, e)


def _tighten(clip: ClipInfo, s: float, e: float) -> tuple[float, float]:
    """Зрізати довгу тишу на початку/в кінці шматка."""
    for a, b in clip.silences:
        if a <= s + 0.05 and b > s and (e - (b - 0.15)) >= MIN_SHOT:
            s = max(s, b - 0.15)
        if a < e and b >= e - 0.05 and ((a + 0.2) - s) >= MIN_SHOT:
            e = min(e, a + 0.2)
    return s, e


def _scene_ranges(clip: ClipInfo) -> list[tuple[float, float]]:
    cuts = [0.0] + [c for c in clip.scenes if 0 < c < clip.duration] + [clip.duration]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= MIN_SHOT]


def _filter(clips: Iterable[ClipInfo], mask: str | None) -> list[ClipInfo]:
    if not mask:
        return list(clips)
    return [c for c in clips if fnmatch.fnmatch(c.file.lower(), mask.lower())
            or fnmatch.fnmatch(c.file.rsplit("/", 1)[-1].lower(), mask.lower())]


# ---------- кандидати ----------

def window_candidates(clip: ClipInfo, dur: float) -> list[Shot]:
    """Шматки заданої тривалості в межах однієї сцени, з оцінкою якості."""
    out = []
    for a, b in _scene_ranges(clip):
        d = min(dur, b - a)
        t = a + (0.15 if b - a > d + 0.3 else 0.0)
        while t + d <= b + 1e-6:
            s, e = _snap_words(clip, t, t + d)
            score = (_brightness_score(clip, s, e) * 0.6
                     + (1 - _silence_ratio(clip, s, e)) * 0.3
                     + min(1.0, (e - s) / dur) * 0.1)
            if clip.words and any(s <= w.s < e for w in clip.words):
                score += 0.05
            out.append(Shot(clip.file, round(s, 3), round(e, 3), round(score, 3), "якісний фрагмент"))
            t += max(d, 1.0)
    return out


def phrase_candidates(clip: ClipInfo, phrase: str, dur: float | None) -> list[Shot]:
    want = norm_tokens(phrase)
    if not want or not clip.words:
        return []
    have = [norm_tokens(w.w)[:1] or [""] for w in clip.words]
    have = [h[0] for h in have]
    out = []
    n = len(want)
    for i in range(len(have)):
        # дозволяємо 1 «зайве» слово всередині фрази
        j, k, hits = i, 0, 0
        while j < len(have) and k < n and j - i < n + 1:
            if stem_eq(have[j], want[k]):
                hits += 1
                k += 1
            elif k == 0:
                break
            j += 1
        if hits == 0:
            continue
        ratio = hits / n
        if ratio < (0.5 if n > 1 else 1.0):
            continue
        w0, w1 = clip.words[i], clip.words[max(i, j - 1)]
        s, e = w0.s - PAD_BEFORE, w1.e + PAD_AFTER
        if dur and e - s < dur:  # розширити до потрібної тривалості, більше «після»
            extra = dur - (e - s)
            s -= extra * 0.3
            e += extra * 0.7
        s, e = max(0.0, s), min(clip.duration, e)
        s, e = _snap_words(clip, s, e)
        score = ratio * 0.8 + _brightness_score(clip, s, e) * 0.2
        out.append(Shot(clip.file, round(s, 3), round(e, 3), round(score, 3),
                        f"фраза «{' '.join(x.w for x in clip.words[i:j])}»"))
    return out


STOP = {"для", "або", "потім", "щоб", "який", "яка", "яке", "які", "його", "її", "цей", "ця", "там", "тут"}


def look_score(look: str, desc: str) -> float:
    """Яка частка слів із «Що в кадрі» є в описі кліпу (0..1). Грубо, з урахуванням закінчень."""
    want = [t for t in norm_tokens(look) if len(t) >= 3 and t not in STOP]
    have = [t for t in norm_tokens(desc) if len(t) >= 3]
    if not want or not have:
        return 0.0
    return sum(1 for w in want if any(stem_eq(w, h) for h in have)) / len(want)


def _apply_look(shots: list[Shot], slot: Slot, catalog: Catalog) -> list[Shot]:
    """Підняти кандидатів, чий опис у КАТАЛОГу схожий на «Що в кадрі»."""
    if not slot.look:
        return shots
    for sh in shots:
        c = catalog.get(sh.file)
        ls = look_score(slot.look, c.desc if c else "")
        if ls > 0:
            sh.score = round(sh.score + 1.5 * ls, 3)
            sh.reason = f"{sh.reason}; опис схожий на «{slot.look}» ({int(ls * 100)}%)"
    return sorted(shots, key=lambda x: -x.score)


def slot_candidates(slot: Slot, catalog: Catalog) -> list[Shot]:
    return _apply_look(_slot_candidates(slot, catalog), slot, catalog) if not slot.clip \
        else _slot_candidates(slot, catalog)


def _slot_candidates(slot: Slot, catalog: Catalog) -> list[Shot]:
    clips = _filter(catalog.clips, slot.from_)
    if slot.clip:
        c = catalog.get(slot.clip) or next((x for x in catalog.clips if x.file.endswith(slot.clip)), None)
        if c is None:
            raise ValueError(f"Файл {slot.clip} не знайдено в папці")
        s = slot.start or 0.0
        e = slot.end if slot.end is not None else min(c.duration, s + (slot.duration or c.duration))
        main = Shot(c.file, s, min(e, c.duration), 1.0, "вказано в ТЗ")
        return [main] + window_candidates(c, slot.duration or main.duration)
    if slot.find:
        res = [sh for c in clips for sh in phrase_candidates(c, slot.find, slot.duration)]
        if res:
            return sorted(res, key=lambda x: -x.score)
        # фразу не знайдено -> пропонуємо звичайні фрагменти з низькою оцінкою
        fb = [sh for c in clips for sh in window_candidates(c, slot.duration or DEFAULT_ANY)]
        for sh in fb:
            sh.score = round(sh.score * 0.3, 3)
            sh.reason = f"фразу «{slot.find}» не знайдено — замінник"
        return sorted(fb, key=lambda x: -x.score)
    res = [sh for c in clips for sh in window_candidates(c, slot.duration or DEFAULT_ANY)]
    return sorted(res, key=lambda x: -x.score)


def _overlaps(a: Shot, b: Shot) -> bool:
    return a.file == b.file and a.start < b.end and b.start < a.end


# ---------- планувальник ----------

class RulesPlanner:
    name = "rules"

    def make_plans(self, brief: Brief, catalog: Catalog) -> list[Plan]:
        if not catalog.clips:
            raise ValueError("У папці немає відео для монтажу")
        cands = [slot_candidates(s, catalog) for s in brief.slots]
        chosen_per_slot: list[list[Shot]] = [[] for _ in brief.slots]
        plans = []
        for v in range(brief.variations):
            used: list[Shot] = []
            segs = []
            for si, (slot, cs) in enumerate(zip(brief.slots, cands)):
                if not cs:
                    raise ValueError(f"Сегмент {si + 1}: немає жодного кандидата")
                if slot.clip:
                    pick = cs[0]  # точно вказаний шматок однаковий у всіх варіаціях
                else:
                    fresh = [c for c in cs if not any(_overlaps(c, u) for u in used)]
                    novel = [c for c in fresh if not any(_overlaps(c, p) for p in chosen_per_slot[si])]
                    pool = novel or fresh or cs
                    pick = pool[0]
                if not slot.clip:
                    s, e = _tighten(catalog.get(pick.file), pick.start, pick.end)
                    pick = Shot(pick.file, round(s, 3), round(e, 3), pick.score, pick.reason)
                used.append(pick)
                chosen_per_slot[si].append(pick)
                alts = [c for c in cs if not _overlaps(c, pick)]
                # різноманітність: не більше 2 альтернатив з одного файлу
                per_file: dict[str, int] = {}
                diverse = []
                for c in alts:
                    if per_file.get(c.file, 0) < 2:
                        diverse.append(c)
                        per_file[c.file] = per_file.get(c.file, 0) + 1
                    if len(diverse) >= MAX_ALTS:
                        break
                segs.append(Segment(id=f"s{si + 1}", shot=pick, title=slot.title,
                                    subtitles=slot.subtitles, alternatives=diverse, slot=si))
            plans.append(Plan(name=brief.name, source_dir=str(brief.source_path()), format=brief.format,
                              style=brief.style, segments=segs, variation=v + 1, cta=brief.cta,
                              music=brief.music, music_volume=brief.music_volume, overlay=brief.overlay, planner=self.name))
        return plans
