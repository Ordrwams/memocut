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
- `core/brief.py` — читання ТЗ (`load_brief` / `brief_from_text` / `parse_brief`) і запис `brief_to_yaml` (для форми).
  Слоти: `clip`+start/end | `find: фраза` | `any: true`; + title, duration, subtitles, from. `clip` може бути ID з КАТАЛОГ.csv.
  Верхній рівень: + `folders` (підпапки гри), `overlay` (текст на весь ролик), `notes` (вільний текст замовника).
- `core/library.py` — папка гри після каталогізатора: `КАТАЛОГ.csv` (id;…;dest;proxy;text), `_для монтажу/тексти/<ID>.txt`
  (`[хв:сек-хв:сек] текст`), `proxy/<ID>.mp4` (480p, ті самі таймкоди). Аналіз сцен іде по проксі, транскрипт — з txt
  (порожній txt = мови немає, Whisper не запускається). Ніколи не беруться `05_*`, `06_*`, `_*`, `*Фото*`.
- `analyze/catalog.py` — один прохід ffmpeg: сцени, тиша, яскравість/сек, прев'ю. Кеш: `<source>/.memocut/catalog.json` (перерахунок за mtime+size).
- `analyze/transcribe.py` — `<clip>.words.json` → `<clip>.srt` → `тексти/<ID>.txt` гри → faster-whisper.
- `planner/rules.py` — кандидати на слот з оцінкою; варіації беруть різні кандидати; решта → `Segment.alternatives`.
- `planner/base.py:get_planner` — точка підключення `planner/ai.py` (рівень 3, Claude API). Має повертати той самий `list[Plan]`.
- `render/engine.py` — кожен сегмент рендериться окремо, кеш за хешем (`.memocut/render_cache`), склейка concat без перекодування. ffmpeg запускається з `cwd=cache`, щоб уникнути екранування Windows-шляхів у фільтрі subtitles.
- `render/ass.py` — заголовки/субтитри/фінальна картка. Координати завжди 1080-базові (PlayRes), прев'ю = половина роздільності.
- `core/edit.py` — чисті функції правок (повертають новий Plan, revision+1). GUI має викликати лише їх.
- `core/project.py` — повний цикл, ним користуються CLI і GUI.
- `gui/` (PySide6): `main_window.py` (QStackedWidget: ТЗ → прогрес → галерея), `brief_page.py` (форма ТЗ + вкладка YAML;
  обидві працюють з одним dict як у файлі; ТЗ зберігається в `<гра>/MemoCut/ТЗ/`, результати в `<гра>/MemoCut/Результати/`;
  чернетка форми в QSettings `draft_yaml`), `progress_page.py`,
  `gallery.py` (картки варіацій з QMediaPlayer + черга фінальних рендерів), `workers.py` (Job у QThread).
  **Сигнали з Job підключати лише до методів віджетів, не до лямбд** — інакше слот виконається у фоновому потоці.
  Скасування: `Cancelled(BaseException)` кидається з колбеку прогресу. `VariationCard.release()` — відпустити
  файл перед перерендером (Windows блокує відкрите відео). QAudioOutput створюється при першому Play.
- `app.py` / `memocut.spec`: один код → два exe: `MemoCut.exe` (вікно) і `memocut-cli.exe` (консоль).
  Аргумент-команда (`run`, `show`…) → CLI, шлях до .yaml → вікно з відкритим ТЗ.
- `.github/workflows/build-windows.yml` — тести (offscreen) → PyInstaller → FFmpeg BtbN → `MemoCut-windows.zip`.
- `styles/*.yaml` — пресети; відсутні поля беруться з `core/style.py:DEFAULT`. Користувацькі стилі поруч із .exe мають пріоритет.

## Правила
- Без ШІ в робочому циклі. Все локально, офлайн.
- Windows: шляхи через pathlib, subprocess без вікна (`core/proc.py`), ffmpeg.exe у `ffmpeg/` поруч із програмою.
- Нові поля стилю — спершу в `DEFAULT`, потім використання в `render/ass.py`.
- Після змін рендеру підняти `"v"` у `Renderer._key`, щоб скинути кеш.
- Перевірка: `QT_QPA_PLATFORM=offscreen python -m pytest tests` і `python -m memocut run tests/...` на тестових кліпах (див. tests/make_test_clips.py).

## Дорожня карта
1. ✅ Ядро: аналіз, планувальник за правилами, рендер, правки, CLI, збірка .exe
2. ✅ GUI (PySide6): ТЗ у програмі — форма (папка гри з підпапками, сцени/хук, тексти, музика, вільний текст) +
   вкладка YAML (зберегти/відкрити/передати); папка гри MemoGames (каталог, транскрипти, проксі); overlay-текст; → прогрес (журнал, ETA, скасування)
   → галерея прев'ю (QMediaPlayer, грає одне відео), «Експорт MP4» чергою, «Відкрити готові результати».
   Перевірено на Linux offscreen + зібраний PyInstaller-бандл; на Windows ще не запускали.
3. ⬜ Редактор (кнопка «Редагувати» в картці вже є, вимкнена; сигнал `edit_requested(folder)`): стрічка сегментів з мініатюрами, панель альтернатив, «Вибрати файл», повзунок обрізки, текст заголовка, Відмінити (history/)
4. ◐ Фінальний експорт, черга рендерів — базова черга є в `gallery.py`; лишилось: вибір папки/імені експорту,
   кілька ТЗ у черзі, скасування окремого елемента
5. ⬜ Рівень 3: `planner/ai.py` (Claude API, вільний текст ТЗ у `notes`), приклади з history/ як few-shot
