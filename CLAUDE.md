# MemoCut — контекст для Claude

Десктоп-програма для Windows 64-біт: монтує UGC-відео MemoGames за ТЗ (YAML) без ШІ.
Мова інтерфейсу, повідомлень і коментарів — українська.

## Архітектура (3 шари, контракт — `Plan`)
```
brief.yaml ──► analyze/ ──► catalog.json ──► planner/ ──► plan.json ──► render/ ──► mp4
                (ffmpeg, whisper)            (rules | ai)    ▲            (ffmpeg + ASS)
                                                             └── core/edit.py (правки з GUI)
```
- `core/models.py` — Catalog, Plan, Segment, Shot. **Змінювати формат Plan обережно**: збільшити PLAN_VERSION і додати міграцію в `Plan.from_dict`.
- `core/brief.py` — читання ТЗ. Слоти: `clip`+start/end | `find: фраза` | `any: true`; + title, duration, subtitles, from.
- `analyze/catalog.py` — один прохід ffmpeg: сцени, тиша, яскравість/сек, прев'ю. Кеш: `<source>/.memocut/catalog.json` (перерахунок за mtime+size).
- `analyze/transcribe.py` — `<clip>.words.json` → `<clip>.srt` → faster-whisper.
- `planner/rules.py` — кандидати на слот з оцінкою; варіації беруть різні кандидати; решта → `Segment.alternatives`.
- `planner/base.py:get_planner` — точка підключення `planner/ai.py` (рівень 3, Claude API). Має повертати той самий `list[Plan]`.
- `render/engine.py` — кожен сегмент рендериться окремо, кеш за хешем (`.memocut/render_cache`), склейка concat без перекодування. ffmpeg запускається з `cwd=cache`, щоб уникнути екранування Windows-шляхів у фільтрі subtitles.
- `render/ass.py` — заголовки/субтитри/фінальна картка. Координати завжди 1080-базові (PlayRes), прев'ю = половина роздільності.
- `core/edit.py` — чисті функції правок (повертають новий Plan, revision+1). GUI має викликати лише їх.
- `core/project.py` — повний цикл, ним користуються CLI і GUI.
- `styles/*.yaml` — пресети; відсутні поля беруться з `core/style.py:DEFAULT`. Користувацькі стилі поруч із .exe мають пріоритет.

## Правила
- Без ШІ в робочому циклі. Все локально, офлайн.
- Windows: шляхи через pathlib, subprocess без вікна (`core/proc.py`), ffmpeg.exe у `ffmpeg/` поруч із програмою.
- Нові поля стилю — спершу в `DEFAULT`, потім використання в `render/ass.py`.
- Після змін рендеру підняти `"v"` у `Renderer._key`, щоб скинути кеш.
- Перевірка: `python -m pytest tests` і `python -m memocut run tests/...` на тестових кліпах (див. tests/make_test_clips.py).

## Дорожня карта
1. ✅ Ядро: аналіз, планувальник за правилами, рендер, правки, CLI, збірка .exe
2. ⬜ GUI (PySide6): вікно ТЗ → прогрес → галерея 3 прев'ю (QMediaPlayer)
3. ⬜ Редактор: стрічка сегментів з мініатюрами, панель альтернатив, «Вибрати файл», повзунок обрізки, текст заголовка, Відмінити (history/)
4. ⬜ Фінальний експорт, черга рендерів
5. ⬜ Рівень 3: `planner/ai.py` (Claude API, вільний текст ТЗ у `notes`), приклади з history/ як few-shot
