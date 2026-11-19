"""Створює синтетичні тестові кліпи в tests/_clips/raw для ручної перевірки:
    python tests/make_test_clips.py
    python -m memocut run tests/sample_brief.yaml --no-transcripts
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memocut.core.paths import ffmpeg  # noqa: E402

D = Path(__file__).parent / "_clips" / "raw"
D.mkdir(parents=True, exist_ok=True)
F = ffmpeg()


def ff(*a):
    subprocess.run([F, "-v", "error", "-y", *a], check=True, cwd=D)


ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4", "-f", "lavfi", "-i", "smptebars=s=720x1280:r=30:d=4",
   "-f", "lavfi", "-i", "color=c=0x3366aa:s=720x1280:r=30:d=4", "-f", "lavfi", "-i", "sine=f=300:d=12",
   "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v];[3:a]volume='if(between(t,5,6.5),0,1)':eval=frame[a]",
   "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "IMG_0101.mp4")
ff("-f", "lavfi", "-i", "testsrc=s=720x1280:r=30:d=10", "-f", "lavfi", "-i", "sine=f=440:d=10",
   "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "IMG_0102.mp4")
ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=25:d=8", "-c:v", "libx264", "-preset", "ultrafast", "IMG_0103.mp4")
ff("-f", "lavfi", "-i", "color=c=0x080808:s=720x1280:r=30:d=6", "-f", "lavfi", "-i", "sine=f=200:d=6",
   "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "IMG_0104.mp4")


def mk(text, start, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "s": round(t, 2), "e": round(t + step - 0.05, 2)})
        t += step
    return out


(D / "IMG_0101.words.json").write_text(json.dumps(
    mk("Ми грали весь вечір і так сміялися що аж сльози. Це найкраща гра для нас", 0.5)
    + mk("Раджу всім парам спробувати", 7.0), ensure_ascii=False), encoding="utf-8")
(D / "IMG_0102.words.json").write_text(json.dumps(
    mk("Чесно ми сміялись до ночі. Питання дуже глибокі", 1.0, 0.45), ensure_ascii=False), encoding="utf-8")
print("Готово:", D)
