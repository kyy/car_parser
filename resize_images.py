# resize_images.py
"""
Создаёт превью картинок и переносит оригиналы в images_orig/.

Логика:
  images/<file>       → превью (max width 1400, JPEG quality 82)
  images_orig/<file>  → оригинал

В HTML:
  <img src="../images/X" data-orig="../images_orig/X">

Идемпотентно: повторный запуск не портит уже сжатые.
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote
from PIL import Image

from config import OUTPUT_DIR, DOC_ID


# Параметры превью
PREVIEW_MAX_WIDTH = 1400
PREVIEW_JPEG_QUALITY = 82
PREVIEW_MAX_BYTES = 400 * 1024   # 400 KB — если больше, сжимаем сильнее
SKIP_IF_SMALLER = 150 * 1024     # если оригинал < 150 KB — не трогаем


def is_already_preview(path: Path) -> bool:
    """Если размер меньше порога — уже превью."""
    try:
        return path.stat().st_size < SKIP_IF_SMALLER
    except OSError:
        return False


def make_preview(src: Path, dst: Path):
    """Готовит превью из src, сохраняет в dst (JPEG)."""
    with Image.open(src) as im:
        im.load()

        # RGBA/P → RGB на белом фоне (для JPEG)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im_rgba = im.convert("RGBA")
            bg.paste(im_rgba, mask=im_rgba.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        # Уменьшаем, если шире лимита
        if im.width > PREVIEW_MAX_WIDTH:
            ratio = PREVIEW_MAX_WIDTH / im.width
            new_size = (PREVIEW_MAX_WIDTH, int(im.height * ratio))
            im = im.resize(new_size, Image.LANCZOS)

        # Сжимаем с итеративной подгонкой по размеру
        quality = PREVIEW_JPEG_QUALITY
        while True:
            im.save(dst, "JPEG", quality=quality, optimize=True)
            size = dst.stat().st_size
            if size <= PREVIEW_MAX_BYTES or quality <= 40:
                break
            quality -= 10


def process_image_file(img_path: Path, orig_dir: Path) -> tuple[Path, Path] | None:
    """
    Обрабатывает одну картинку.
    Возвращает (preview_path, original_path) или None, если что-то не так.
    """
    if not img_path.exists():
        return None

    # SVG не ресайзим — копируем как есть
    if img_path.suffix.lower() == ".svg":
        orig_path = orig_dir / img_path.name
        if not orig_path.exists():
            orig_path.write_bytes(img_path.read_bytes())
        return img_path, orig_path

    # Уже превью?
    orig_path = orig_dir / img_path.name
    if orig_path.exists():
        # Оригинал уже вынесен — картинка в images/ уже превью
        return img_path, orig_path

    if is_already_preview(img_path):
        # Маленькая — просто копируем в orig, оставляем как есть
        orig_path.write_bytes(img_path.read_bytes())
        return img_path, orig_path

    try:
        # Сохраняем оригинал
        orig_path.write_bytes(img_path.read_bytes())

        # Делаем превью (во временный файл, потом заменяем)
        tmp = img_path.with_suffix(".tmp.jpg")
        make_preview(orig_path, tmp)
        tmp.replace(img_path.with_suffix(".jpg"))
        # Если имя было .png, а стало .jpg — удаляем старый
        if img_path.suffix.lower() != ".jpg":
            new_path = img_path.with_suffix(".jpg")
            if img_path.exists() and img_path != new_path:
                img_path.unlink()
            return new_path, orig_path

        return img_path, orig_path
    except Exception as e:
        print(f"  ⚠️  {img_path.name}: {e}")
        return None


IMG_RE = re.compile(
    r'<img\b[^>]*?src=["\'](?:\.\./)?images/([^"\']+)["\'][^>]*?>',
    re.IGNORECASE,
)


def patch_html(html_path: Path, images_dir: Path, orig_dir: Path) -> int:
    """
    Заменяет в HTML src на превью и добавляет data-orig.
    Возвращает число изменённых картинок.
    """
    html = html_path.read_text(encoding="utf-8")
    changed = 0

    def repl(match):
        nonlocal changed
        full_tag = match.group(0)
        fname = match.group(1)

        # Уже есть data-orig? Не трогаем
        if "data-orig=" in full_tag:
            return full_tag

        img_path = images_dir / fname
        result = process_image_file(img_path, orig_dir)
        if not result:
            return full_tag

        new_preview, new_orig = result
        rel_preview = f"../images/{new_preview.name}"
        rel_orig = f"../images_orig/{new_orig.name}"

        # Меняем src и добавляем data-orig
        new_tag = re.sub(
            r'src=["\'][^"\']+["\']',
            f'src="{rel_preview}"',
            full_tag,
            count=1,
        )
        if 'data-orig=' not in new_tag:
            new_tag = new_tag[:-1] + f' data-orig="{rel_orig}">'

        changed += 1
        return new_tag

    new_html = IMG_RE.sub(repl, html)

    if new_html != html:
        html_path.write_text(new_html, encoding="utf-8")
    return changed


def main():
    out_root = Path(OUTPUT_DIR) / DOC_ID
    images_dir = out_root / "images"
    orig_dir = out_root / "images_orig"
    orig_dir.mkdir(parents=True, exist_ok=True)

    if not images_dir.exists():
        print(f"❌ Нет папки {images_dir}")
        sys.exit(1)

    html_dirs = [out_root / "pages", out_root / "ru_pages"]

    total_imgs = 0
    total_pages = 0

    for hdir in html_dirs:
        if not hdir.exists():
            continue

        files = sorted(hdir.glob("*.html"))
        print(f"📂 {hdir.name}: {len(files)} файлов")

        for i, html_file in enumerate(files, 1):
            n = patch_html(html_file, images_dir, orig_dir)
            total_imgs += n
            if n:
                total_pages += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(files)}]...")

    print(f"\n✅ Обработано: {total_imgs} картинок в {total_pages} страницах")
    print(f"   Превью:  {images_dir}")
    print(f"   Оригиналы: {orig_dir}")


if __name__ == "__main__":
    main()