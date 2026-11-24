"""Рисует аватар бота: свеча в темноте. Без внешних ассетов — только Pillow.

    python scripts/make_avatar.py [путь]

512×512 PNG, безопасно для круглой обрезки в Telegram.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 512
CENTER = (S // 2, S // 2)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))  # type: ignore[return-value]


def radial_background() -> Image.Image:
    """Тёмный фон с фиолетовым свечением в центре."""
    small = Image.new("RGB", (128, 128))
    px = small.load()
    inner = (34, 26, 58)
    outer = (8, 7, 13)
    for y in range(128):
        for x in range(128):
            dx = (x - 64) / 64
            dy = (y - 58) / 64
            d = min(1.0, math.hypot(dx, dy) ** 1.35)
            px[x, y] = mix(inner, outer, d)
    return small.resize((S, S), Image.BICUBIC)


def glow(center: tuple[int, int], radius: int, color: tuple[int, int, int],
         strength: float) -> Image.Image:
    layer = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(layer)
    steps = 26
    for i in range(steps, 0, -1):
        r = int(radius * i / steps)
        v = int(255 * strength * (1 - i / steps) ** 1.6)
        d.ellipse([center[0] - r, center[1] - r, center[0] + r, center[1] + r], fill=v)
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 5))
    tint = Image.new("RGB", (S, S), color)
    return Image.composite(tint, Image.new("RGB", (S, S), (0, 0, 0)), layer)


def flame_mask(cx: int, cy: int, w: int, h: int, tip: int, lean: int) -> Image.Image:
    """Пламя одним куском: круглое брюшко + треугольный кончик, слитые в маску.

    Раньше кончик строился отдельным многоугольником и отрывался от пламени —
    здесь объединение гарантирует непрерывность.
    """
    mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=255)
    d.polygon([(cx - int(w * 0.52), cy),
               (cx + int(w * 0.52), cy),
               (cx + lean, cy - h // 2 - tip)], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(2))


def main(out: Path) -> None:
    img = radial_background().convert("RGB")

    # 1. Свечение вокруг пламени (аддитивно)
    flame_xy = (S // 2, 168)
    img = ImageChops.screen(img, glow(flame_xy, 190, (255, 168, 60), 0.55))
    img = ImageChops.screen(img, glow((S // 2, 300), 220, (255, 140, 40), 0.16))

    draw = ImageDraw.Draw(img, "RGBA")

    # 2. Свеча
    body = [206, 236, 306, 452]
    draw.rounded_rectangle(body, radius=14, fill=(232, 219, 190))
    # тень справа
    draw.rounded_rectangle([280, 236, 306, 452], radius=14, fill=(196, 180, 150))
    # оплывший воск сверху
    draw.ellipse([200, 224, 312, 268], fill=(240, 229, 205))
    draw.ellipse([212, 232, 300, 258], fill=(250, 242, 222))
    # фитиль
    draw.line([(256, 236), (256, 214)], fill=(40, 30, 24), width=5)

    # 3. Пламя: внешнее оранжевое, среднее жёлтое, ядро белое
    for scale, color, dy, lean in ((1.0, (255, 118, 24), 0, 8),
                                   (0.70, (255, 186, 56), 6, 6),
                                   (0.36, (255, 249, 220), 12, 3)):
        w = int(78 * scale)
        h = int(92 * scale)
        tip = int(72 * scale)
        mask = flame_mask(S // 2, flame_xy[1] + 42 + dy, w, h, tip, lean)
        if scale < 1.0:
            mask = mask.filter(ImageFilter.GaussianBlur(2))
        layer = Image.new("RGBA", (S, S), color + (255,))
        img.paste(layer, (0, 0), mask)

    # 4. Виньетка по краям
    vig = Image.new("L", (S, S), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-90, -90, S + 90, S + 90], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(70))
    dark = Image.new("RGB", (S, S), (4, 4, 8))
    img = Image.composite(img, dark, vig)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print("готово:", out, img.size)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/avatar.png"))
