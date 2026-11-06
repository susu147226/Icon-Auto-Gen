"""把单张源图渲染成各平台规范的 RGBA 图标。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "presets"


def load_preset(preset_id: str) -> dict:
    path = PRESETS / f"{preset_id}.json"
    if not path.exists():
        known = ", ".join(p.stem for p in sorted(PRESETS.glob("*.json")))
        raise SystemExit(f"未知 preset: {preset_id}（可用: {known}）")
    return json.loads(path.read_text(encoding="utf-8"))


def make_mask(side: int, shape: str, corner: float | None) -> Image.Image:
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    if shape == "circle":
        draw.ellipse((0, 0, side - 1, side - 1), fill=255)
    elif shape in ("rounded_rect", "squircle"):
        radius = int(round(side * (corner or 0.25)))
        draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=255)
    else:
        mask = Image.new("L", (side, side), 255)
    return mask


def render(source: Image.Image, preset: dict, shape: str | None = None) -> Image.Image:
    canvas = preset["canvas"][0]
    style = preset["style"]
    shape = shape or style["shape"]

    side = round(canvas * style["content_ratio"])
    content = source.convert("RGBA").resize((side, side), Image.LANCZOS)

    if shape not in ("system_mask", "square"):
        mask = make_mask(side, shape, style.get("corner_ratio"))
        content.putalpha(ImageChops.multiply(content.getchannel("A"), mask))

    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    offset = (canvas - side) // 2
    out.paste(content, (offset, offset), content)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="按平台规范渲染图标")
    parser.add_argument("--preset", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", default=str(ROOT / "out"), type=Path)
    parser.add_argument("--shape", default=None, help="覆盖形状: square/rounded_rect/squircle/circle")
    args = parser.parse_args()

    preset = load_preset(args.preset)
    source = Image.open(args.input).convert("RGBA")
    icon = render(source, preset, args.shape)

    target = args.out / args.preset
    target.mkdir(parents=True, exist_ok=True)
    dest = target / f"{args.package}.png"
    icon.save(dest)
    print(f"{dest}  {icon.size}")


if __name__ == "__main__":
    main()
