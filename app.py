"""Точка входу для .exe.

  MemoCut.exe                  — вікно програми (GUI)
  MemoCut.exe ТЗ.yaml          — вікно з уже відкритим ТЗ (можна перетягнути файл на .exe)
  memocut-cli.exe run ТЗ.yaml  — командний рядок (див. memocut/cli.py)
"""
import os
import sys

CLI_COMMANDS = {"run", "analyze", "render", "show", "alt", "trim", "replace", "styles", "-h", "--help"}


def _ensure_streams() -> None:
    """У віконному .exe немає консолі (stdout = None) — пишемо вивід CLI у журнал."""
    if sys.stdout is None or sys.stderr is None:
        from memocut.core.paths import user_data_dir
        f = open(user_data_dir() / "cli.log", "a", encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in CLI_COMMANDS:
        _ensure_streams()
        from memocut.cli import main as cli_main
        return cli_main(args)
    if os.path.basename(sys.executable).lower().startswith("memocut-cli"):
        _ensure_streams()
        from memocut.cli import main as cli_main
        return cli_main(args or ["--help"])
    from memocut.gui import run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
