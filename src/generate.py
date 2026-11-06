"""风格冻结与批量生成。"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from postprocess import ROOT
from providers import get_provider

STYLE_FILE = ROOT / "style.json"
GEN_DIR = ROOT / "out" / "gen"


def parse_size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


def read_icons(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            yield row["package"].strip(), (row.get("description") or "").strip(), (row.get("source") or "").strip()


def load_style() -> dict:
    if not STYLE_FILE.exists():
        raise SystemExit("缺少 style.json —— 先跑 pilot 出候选，再跑 freeze 冻结风格")
    return json.loads(STYLE_FILE.read_text(encoding="utf-8"))


def build_prompt(style: dict, description: str) -> str:
    parts = [style.get("style_prompt", ""), description, "应用图标", "主体居中", "构图简洁"]
    return "，".join(p for p in parts if p)


def cmd_pilot(args) -> None:
    provider = get_provider(args.provider)
    outdir = ROOT / "out" / "_pilot"
    outdir.mkdir(parents=True, exist_ok=True)
    images = provider.generate(
        args.prompt,
        negative=args.negative,
        n=args.n,
        size=parse_size(args.size),
        seed=args.seed,
    )
    for i, image in enumerate(images, 1):
        image.save(outdir / f"cand-{i}.png")
        meta = {
            "prompt": args.prompt,
            "negative": args.negative,
            "provider": args.provider,
            "seed": None if args.seed is None else args.seed + i - 1,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        (outdir / f"cand-{i}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"候选 {len(images)} 张 -> {outdir}")


def cmd_freeze(args) -> None:
    candidate = Path(args.candidate)
    if not candidate.is_absolute():
        candidate = ROOT / "out" / "_pilot" / candidate
    if not candidate.exists():
        raise SystemExit(f"候选图不存在: {candidate}")

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    Image.open(candidate).save(assets / "style-ref.png")

    meta_path = candidate.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    seed = args.seed if args.seed is not None else meta.get("seed")
    style = {
        "reference_image": "assets/style-ref.png",
        "style_prompt": args.style_prompt,
        "negative_prompt": args.negative,
        "provider": args.provider or meta.get("provider", "seedream"),
        "size": args.size,
        "seed": seed,
        "frozen_from": str(candidate.relative_to(ROOT)) if candidate.is_relative_to(ROOT) else str(candidate),
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
    }
    STYLE_FILE.write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"风格已冻结 -> {STYLE_FILE}")


def cmd_batch(args) -> None:
    style = load_style()
    provider = get_provider(style["provider"])
    items = list(read_icons(Path(args.icons)))

    todo = []
    for package, description, source in items:
        if source:
            continue
        if not args.force and (GEN_DIR / package / "raw.png").exists():
            continue
        todo.append((package, description))

    skipped = len(items) - len(todo)
    print(f"共 {len(items)} 个，已完成跳过 {skipped} 个，待生成 {len(todo)} 个")
    if not todo:
        return

    reference = ROOT / style["reference_image"] if args.use_ref else None
    for index, (package, description) in enumerate(todo, 1):
        prompt = build_prompt(style, description)
        seed = None if style.get("seed") is None else int(style["seed"]) + index
        images = provider.generate(
            prompt,
            negative=style.get("negative_prompt", ""),
            reference=reference,
            n=1,
            size=tuple(style.get("size", [1024, 1024])),
            seed=seed,
        )
        outdir = GEN_DIR / package
        outdir.mkdir(parents=True, exist_ok=True)
        images[0].save(outdir / "raw.png")
        meta = {
            "package": package,
            "description": description,
            "prompt": prompt,
            "negative": style.get("negative_prompt", ""),
            "provider": style["provider"],
            "seed": seed,
            "reference": str(reference.relative_to(ROOT)) if reference else None,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        (outdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{index}/{len(todo)}] {package} ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="风格冻结与批量生图")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pilot = sub.add_parser("pilot", help="对单个图标出多个候选")
    pilot.add_argument("--provider", required=True, choices=["seedream", "gptimage", "comfyui"])
    pilot.add_argument("--prompt", required=True)
    pilot.add_argument("--negative", default="")
    pilot.add_argument("--n", type=int, default=4)
    pilot.add_argument("--size", default="1024x1024")
    pilot.add_argument("--seed", type=int, default=None)
    pilot.set_defaults(func=cmd_pilot)

    freeze = sub.add_parser("freeze", help="把选中的候选冻结成风格")
    freeze.add_argument("--candidate", required=True, help="候选文件名，如 cand-3.png")
    freeze.add_argument("--style-prompt", required=True, help="从选定图反推的风格描述")
    freeze.add_argument("--negative", default="")
    freeze.add_argument("--provider", default=None, choices=["seedream", "gptimage", "comfyui"])
    freeze.add_argument("--size", default="1024x1024")
    freeze.add_argument("--seed", type=int, default=None)
    freeze.set_defaults(func=cmd_freeze)

    batch = sub.add_parser("batch", help="按冻结的风格批量生成")
    batch.add_argument("--icons", required=True, type=Path)
    batch.add_argument("--force", action="store_true", help="已有的也重跑")
    batch.add_argument("--use-ref", action="store_true", help="把风格参考图作为图生图输入")
    batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
