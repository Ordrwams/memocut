"""Точка входу для .exe. На етапі 2 тут запускатиметься вікно (GUI), якщо немає аргументів."""
import sys

from memocut.cli import main

if __name__ == "__main__":
    sys.exit(main())
