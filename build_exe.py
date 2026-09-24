# build_exe.py
"""
Собирает .exe (или бинарник под Linux/macOS) через PyInstaller.

Эквивалент команды:
    pyinstaller --noconfirm --clean --onefile --windowed ^
        --name "Guide" ^
        --add-data "output/56746;site" ^
        --icon "icon.ico" ^
        --add-data "icon.ico;." ^
        launcher.py

Запуск:
    python build_exe.py

При желании можно переопределить через аргументы:
    python build_exe.py --name MyGuide --doc 12345 --entry launcher.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import DOC_ID, OUTPUT_DIR

# ============================================================
# Значения по умолчанию (то, что вы просили)
# ============================================================
out_root = Path(OUTPUT_DIR) / DOC_ID
content_path = out_root / "content.ru.json"
if not content_path.is_file():
    content_path = out_root  / "content.json"

with content_path.open(encoding="utf-8") as f:
    doc_title = json.load(f)
DEFAULT_NAME = doc_title.get("doc_title", "Руководство")
DEFAULT_DOC = DOC_ID
DEFAULT_ENTRY = "launcher.py"
DEFAULT_ICON = "icon.ico"
OUTPUT_ROOT = "output"                # где лежит папка с контентом
SITE_INTERNAL = "site"                # как папка называется внутри .exe


# ============================================================
# Вспомогательное
# ============================================================

def sep() -> str:
    """Разделитель источник-назначение для --add-data."""
    # Windows: ';', Linux/macOS: ':'
    return ";" if os.name == "nt" else ":"


def check_pyinstaller() -> None:
    """Проверяет, что pyinstaller доступен в PATH."""
    if shutil.which("pyinstaller") is None:
        print("PyInstaller не найден в PATH.")
        print("Установите: pip install pyinstaller")
        raise SystemExit(1)


def check_paths(entry: Path, icon: Path, site_dir: Path) -> None:
    """Проверяет, что всё нужное на месте, и печатает статус."""
    problems: list[str] = []

    if not entry.is_file():
        problems.append(f"нет файла: {entry}")

    if not site_dir.is_dir():
        problems.append(f"нет папки:  {site_dir}")

    if not (site_dir / "index.html").is_file():
        problems.append(f"нет файла:  {site_dir / 'index.html'} "
                        f"(папка контента выглядит пустой)")

    if not icon.is_file():
        # Иконка не критична — соберём без неё, но предупредим.
        print(f"Внимание: {icon} не найден — сборка без иконки.")
        icon = None

    if problems:
        print("\nНе могу начать сборку:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(2)

    return icon


# ============================================================
# Сборка команды
# ============================================================

def build_command(
    name: str,
    entry: Path,
    icon: Path | None,
    site_dir: Path,
) -> list[str]:
    s = sep()
    cmd: list[str] = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", name,
        "--add-data", f"{site_dir}{s}{SITE_INTERNAL}",
    ]

    if icon is not None:
        cmd += ["--icon", str(icon)]
        # Кладём icon.ico внутрь архива — пригодится для иконки окна
        # (resource_root() / "icon.ico" в launcher.py).
        cmd += ["--add-data", f"{icon}{s}."]

    cmd.append(str(entry))
    return cmd


# ============================================================
# Main
# ============================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Сборка .exe через PyInstaller (обёртка над командой).",
    )
    p.add_argument("--name", default=DEFAULT_NAME,
                   help=f"имя выходного файла (по умолчанию: {DEFAULT_NAME})")
    p.add_argument("--doc", default=DEFAULT_DOC,
                   help=f"ID документа (папка внутри {OUTPUT_ROOT}/, "
                        f"по умолчанию: {DEFAULT_DOC})")
    p.add_argument("--entry", default=DEFAULT_ENTRY,
                   help=f"точка входа (по умолчанию: {DEFAULT_ENTRY})")
    p.add_argument("--icon", default=DEFAULT_ICON,
                   help=f"файл иконки .ico (по умолчанию: {DEFAULT_ICON})")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    entry = Path(args.entry).resolve()
    icon = Path(args.icon).resolve()
    site_dir = (Path(OUTPUT_ROOT) / args.doc).resolve()

    print("Проверка окружения...")
    check_pyinstaller()

    print("Проверка исходников...")
    icon = check_paths(entry, icon, site_dir)
    print(f"  entry: {entry}")
    print(f"  site : {site_dir}")
    if icon:
        print(f"  icon : {icon}")

    cmd = build_command(args.name, entry, icon, site_dir)

    print("\nКоманда:")
    print("  " + " ".join(str(x) if " " not in str(x) else f'"{x}"'
                          for x in cmd))
    print()

    # Запускаем сборку в текущей папке.
    try:
        proc = subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        return 130

    if proc.returncode != 0:
        print(f"\nPyInstaller вернул код {proc.returncode}.")
        return proc.returncode

    exe_name = args.name + (".exe" if os.name == "nt" else "")
    out_path = Path("dist") / exe_name
    print("\nГотово.")
    if out_path.is_file():
        print(f"  {out_path.resolve()}")
    else:
        print(f"  Ожидался файл: {out_path.resolve()} (проверьте вручную)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())