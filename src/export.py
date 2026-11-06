"""按平台规范批量渲染并打包。"""
from __future__ import annotations

import argparse
import csv
import zipfile
from pathlib import Path

from PIL import Image, ImageFilter

from postprocess import ROOT, load_preset, render

PRESET_IDS = ["huawei", "honor", "oppo", "vivo", "harmony"]


def read_batch(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            package = row["package"].strip()
            source = (row.get("source") or "").strip()
            yield package, Path(source) if source else ROOT / "out" / "gen" / package / "raw.png"


def split_layers(source: Image.Image, preset: dict) -> dict[str, Image.Image]:
    canvas = tuple(preset["canvas"])
    base = source.convert("RGB").resize(canvas, Image.LANCZOS)
    return {
        "background": base.filter(ImageFilter.GaussianBlur(16)).convert("RGBA"),
        "foreground": source.convert("RGBA").resize(canvas, Image.LANCZOS),
    }


def write_index(preset: dict, entries: list[tuple[str, str]], staging: Path) -> None:
    index = preset.get("index")
    if not index:
        return
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<iconinfo>"]
    lines += [index["template"].format(package=pkg, file=name) for pkg, name in entries]
    lines.append("</iconinfo>")
    dest = staging / index["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pack(preset: dict, staging: Path, out: Path) -> Path:
    container = preset.get("container", {})
    if container.get("type") != "zip":
        return staging
    name = container["archive"]
    suffix = "" if Path(name).suffix else ".zip"
    archive = out / f"{preset['id']}_{name}{suffix}"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(staging).as_posix())
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="批量渲染并打包图标")
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--presets", default="all")
    parser.add_argument("--out", default=str(ROOT / "export"), type=Path)
    args = parser.parse_args()

    ids = PRESET_IDS if args.presets == "all" else [p.strip() for p in args.presets.split(",")]
    items = list(read_batch(args.batch))
    if not items:
        raise SystemExit(f"批次为空: {args.batch}")

    for pid in ids:
        preset = load_preset(pid)
        staging = args.out / pid
        entries: list[tuple[str, str]] = []

        for package, src in items:
            source = Image.open(src).convert("RGBA")
            if preset["layered"]:
                for layer, img in split_layers(source, preset).items():
                    dest = staging / preset["path"].format(package=package, layer=layer)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    img.save(dest)
            else:
                dest = staging / preset["path"].format(package=package)
                dest.parent.mkdir(parents=True, exist_ok=True)
                render(source, preset).save(dest)
                entries.append((package, f"{package}.png"))

        write_index(preset, entries, staging)
        result = pack(preset, staging, args.out)
        print(f"{pid:8s} {len(items):3d} 个 -> {result}")


if __name__ == "__main__":
    main()
