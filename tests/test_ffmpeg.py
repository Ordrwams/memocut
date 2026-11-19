"""Інтеграційний тест на справжньому ffmpeg (у CI — та сама збірка BtbN, що йде в програму).

Відео одним планом без склейок (саме на такому падав аналіз у новому ffmpeg), озвучка (підміна ElevenLabs),
музика, субтитри з озвучки, фінальна картка. Пропускається, якщо ffmpeg не знайдено.
"""
import subprocess
from pathlib import Path

import pytest

from memocut.core import paths, project


def _ff():
    try:
        return paths.ffmpeg()
    except RuntimeError:
        pytest.skip("ffmpeg не знайдено")


def test_oneshot_video_with_voiceover(tmp_path, monkeypatch):
    ff = _ff()
    raw = tmp_path / "02_Сирі"
    raw.mkdir()

    def make(*a):
        subprocess.run([ff, "-v", "error", "-y", *a], check=True)

    make("-f", "lavfi", "-i", "testsrc2=s=480x854:r=30:d=12", "-c:v", "libx264", "-preset", "ultrafast",
         str(raw / "oneshot.MOV"))                                    # без склейок і без звуку
    make("-f", "lavfi", "-i", "sine=f=220:d=6", str(tmp_path / "vo.mp3"))
    make("-f", "lavfi", "-i", "sine=f=440:d=3", str(tmp_path / "music.mp3"))
    words = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.45} for i, w in enumerate("Teach your kid to ask questions".split())]
    monkeypatch.setattr(project, "synthesize", lambda text, cfg, out, voice: (tmp_path / "vo.mp3", words))

    brief = tmp_path / "tz.yaml"
    brief.write_text(f"""name: 'Тест'
source_dir: '{tmp_path.as_posix()}'
folders: ['02_Сирі']
variations: 1
segments:
  - any: true
    title: 'Хук'
    duration: 2
  - any: true
    duration: 2
voiceover: 'Teach your kid to ask questions'
voice: 'x'
music: '{(tmp_path / "music.mp3").as_posix()}'
cta: 'Get it today'
""", encoding="utf-8")
    out = project.generate(brief, tmp_path / "out", transcripts=False)
    plan = project.Plan.load(out[0] / "plan.json")
    assert plan.duration == pytest.approx(0.2 + 6.0 + 0.5, abs=0.15)   # сцени підігнані під озвучку
    assert plan.original_volume == 0.2 and plan.voiceover_words
    final = project.rerender(out[0], preview=False)
    dur = float(subprocess.run([paths.ffprobe(), "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout)
    assert dur == pytest.approx(plan.duration + 2.5, abs=0.3)
