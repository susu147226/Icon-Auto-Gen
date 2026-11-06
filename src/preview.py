"""生成五家渲染结果的静态预览页。"""
from __future__ import annotations

import base64
import csv
import io
from pathlib import Path

from PIL import Image

from postprocess import ROOT, load_preset, render

PRESET_IDS = ["huawei", "honor", "oppo", "vivo", "harmony"]
LABELS = {
    "huawei": "华为 4.0",
    "honor": "荣耀",
    "oppo": "OPPO",
    "vivo": "vivo",
    "harmony": "鸿蒙",
}

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>图标预览</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 32px; color: #1a1a1a; background: #fafafa; }}
  h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  table {{ border-collapse: separate; border-spacing: 0; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ padding: 14px 16px; text-align: center; border-bottom: 1px solid #eee; }}
  th {{ font-size: 12px; font-weight: 600; color: #666; background: #f5f5f5; }}
  td.name {{ text-align: left; font-size: 13px; min-width: 200px; }}
  td.name code {{ display: block; color: #999; font-size: 11px; margin-top: 2px; }}
  img {{ width: 96px; height: 96px; image-rendering: auto; }}
  tr:last-child td {{ border-bottom: none; }}
</style>
</head>
<body>
<h1>图标预览</h1>
<div class="meta">{count} 个图标 · raw 为生成原图，右侧为五家规范渲染</div>
<table>
<thead><tr><th>图标</th><th>raw</th>{heads}</tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>
"""


def data_uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def read_icons(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            yield row["package"].strip(), (row.get("description") or "").strip(), (row.get("source") or "").strip()


def main() -> None:
    icons_csv = ROOT / "icons.csv"
    rows = []
    count = 0

    for package, description, source in read_icons(icons_csv):
        raw_path = Path(source) if source else ROOT / "out" / "gen" / package / "raw.png"
        if not raw_path.exists():
            continue
        raw = Image.open(raw_path).convert("RGBA")
        cells = [f'<td><img src="{data_uri(raw)}" title="raw"></td>']
        for pid in PRESET_IDS:
            icon = render(raw, load_preset(pid))
            cells.append(f'<td><img src="{data_uri(icon)}" title="{pid}"></td>')
        rows.append(
            f'<tr><td class="name">{description or "—"}<code>{package}</code></td>{"".join(cells)}</tr>'
        )
        count += 1

    heads = "".join(f"<th>{LABELS[p]}</th>" for p in PRESET_IDS)
    html = PAGE.format(count=count, heads=heads, rows="\n".join(rows))
    dest = ROOT / "out" / "preview.html"
    dest.write_text(html, encoding="utf-8")
    print(f"{count} 个图标 -> {dest}")


if __name__ == "__main__":
    main()
