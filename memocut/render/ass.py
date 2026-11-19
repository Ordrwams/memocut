"""Генерація ASS-файлу (заголовок + субтитри) для одного сегмента.

Координати завжди в «повній» роздільності (1080 по ширині), libass сам
масштабує для прев'ю — тому прев'ю й фінал виглядають однаково.
"""
from __future__ import annotations

from ..core.models import ClipInfo, Segment

ALIGN = {"top": 8, "center": 5, "bottom": 2}


def color(hex_: str, alpha: int = 0) -> str:
    h = hex_.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def inline_color(hex_: str) -> str:
    h = hex_.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _style_line(name: str, font: str, st: dict) -> str:
    box = st.get("box", False)
    if box:  # у режимі плашки libass фарбує плашку кольором обводки
        outline = back = color(st.get("box_color", "#000000"), 0x50)
    else:
        outline, back = color(st["outline_color"]), color("#000000", 0x80)
    return (f"Style: {name},{font},{st['size']},{color(st['color'])},{color(st.get('highlight_color', st['color']))},"
            f"{outline},{back},{-1 if st.get('bold') else 0},0,0,0,100,100,0,0,"
            f"{3 if box else 1},{st['outline']},{st.get('shadow', 0)},{ALIGN.get(st['position'], 2)},"
            f"60,60,{st['margin_v']},1")


def header(w: int, h: int, style: dict) -> str:
    font = style["font"]
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Title", font, style["title"]),
        _style_line("Sub", font, style["subtitles"]),
        _style_line("Overlay", font, style["overlay"]),
        _style_line("End", font, {**style["end_card"], "outline": 0, "outline_color": "#000000",
                                  "bold": True, "position": "center", "margin_v": 0}),
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])


def _anim(kind: str) -> str:
    if kind == "pop":
        return r"{\fscx70\fscy70\t(0,180,\fscx108\fscy108)\t(180,280,\fscx100\fscy100)\fad(120,200)}"
    if kind == "slide":
        return r"{\fad(150,200)\fsp8\t(0,300,\fsp0)}"
    if kind == "none":
        return ""
    return r"{\fad(250,200)}"


def word_groups(words, max_words: int, gap: float = 0.6):
    group = []
    for w in words:
        if group and (len(group) >= max_words or w.s - group[-1].e > gap):
            yield group
            group = []
        group.append(w)
        if w.w.rstrip().endswith((".", "!", "?")):
            yield group
            group = []
    if group:
        yield group


def segment_ass(seg: Segment, clip: ClipInfo | None, style: dict, w: int, h: int,
                overlay: str | None = None) -> str:
    dur = seg.shot.duration
    lines = [header(w, h, style)]
    if overlay:  # рендериться в кожному сегменті — у склейці виглядає як один напис
        lines.append(f"Dialogue: 2,{ts(0)},{ts(dur)},Overlay,,0,0,0,,{esc(overlay)}")
    tst = style["title"]
    if seg.title:
        text = seg.title.upper() if tst.get("uppercase") else seg.title
        lines.append(f"Dialogue: 1,{ts(0)},{ts(dur)},Title,,0,0,0,,{_anim(tst.get('animation', 'fade'))}{esc(text)}")

    sst = style["subtitles"]
    if seg.subtitles and clip and clip.words:
        s0, s1 = seg.shot.start, seg.shot.end
        words = [x for x in clip.words if x.e > s0 + 0.05 and x.s < s1 - 0.05]
        groups = list(word_groups(words, int(sst.get("words_per_line", 4))))
        hl = inline_color(sst.get("highlight_color", sst["color"]))
        base = inline_color(sst["color"])
        up = sst.get("uppercase")
        for gi, g in enumerate(groups):
            g_end = g[-1].e + 0.25
            if gi + 1 < len(groups):
                g_end = min(g_end, groups[gi + 1][0].s)
            texts = [esc(x.w.upper() if up else x.w) for x in g]
            if sst.get("karaoke", True):
                for wi, wd in enumerate(g):
                    a = wd.s if wi else g[0].s
                    b = g[wi + 1].s if wi + 1 < len(g) else g_end
                    parts = [(f"{{\\c{hl}}}{t}{{\\c{base}}}" if k == wi else t) for k, t in enumerate(texts)]
                    lines.append(f"Dialogue: 0,{ts(a - s0)},{ts(min(b, s1) - s0)},Sub,,0,0,0,,{' '.join(parts)}")
            else:
                lines.append(f"Dialogue: 0,{ts(g[0].s - s0)},{ts(min(g_end, s1) - s0)},Sub,,0,0,0,,{' '.join(texts)}")
    return "\n".join(lines) + "\n"


def end_card_ass(text: str, style: dict, w: int, h: int, dur: float) -> str:
    return header(w, h, style) + f"\nDialogue: 0,{ts(0)},{ts(dur)},End,,0,0,0,,{{\\fad(200,0)}}{esc(text)}\n"
