"""生图后端适配层：统一接口，按名字取实现。"""
from __future__ import annotations

import base64
import io
import json
import os
import time
import uuid
from pathlib import Path

import requests
from PIL import Image


class Provider:
    name = "base"

    def generate(
        self,
        prompt: str,
        *,
        negative: str = "",
        reference: Path | None = None,
        size: tuple[int, int] = (1024, 1024),
        n: int = 1,
        seed: int | None = None,
    ) -> list[Image.Image]:
        raise NotImplementedError


def _decode(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


def _data_url(path: Path) -> str:
    raw = path.read_bytes()
    fmt = (Image.open(io.BytesIO(raw)).format or "PNG").lower()
    return f"data:image/{fmt};base64," + base64.b64encode(raw).decode()


class SeedreamProvider(Provider):
    name = "seedream"
    endpoint = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    t2i_model = "doubao-seedream-3-0-t2i-250415"
    i2i_model = "doubao-seededit-3-0-i2i-250415"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ARK_API_KEY") or os.environ.get("VOLCENGINE_API_KEY")
        if not self.api_key:
            raise RuntimeError("缺少环境变量 ARK_API_KEY 或 VOLCENGINE_API_KEY")

    def generate(self, prompt, *, negative="", reference=None, size=(1024, 1024), n=1, seed=None):
        images: list[Image.Image] = []
        for i in range(n):
            body = {
                "model": self.i2i_model if reference else self.t2i_model,
                "prompt": prompt,
                "size": f"{size[0]}x{size[1]}",
                "response_format": "b64_json",
                "watermark": False,
            }
            if negative:
                body["negative_prompt"] = negative
            if seed is not None:
                body["seed"] = seed + i
            if reference:
                body["image"] = _data_url(reference)
            resp = requests.post(
                self.endpoint,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                timeout=300,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"Seedream {resp.status_code}: {resp.text[:500]}")
            images.extend(_decode(item["b64_json"]) for item in resp.json()["data"])
        return images


class GptImageProvider(Provider):
    name = "gptimage"
    base = "https://api.openai.com/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("缺少环境变量 OPENAI_API_KEY")

    def generate(self, prompt, *, negative="", reference=None, size=(1024, 1024), n=1, seed=None):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        common = {"model": "gpt-image-1", "prompt": prompt, "size": f"{size[0]}x{size[1]}", "n": n}
        if reference:
            files = {"image": (reference.name, reference.read_bytes())}
            data = {k: str(v) for k, v in common.items()}
            resp = requests.post(f"{self.base}/images/edits", headers=headers, data=data, files=files, timeout=600)
        else:
            resp = requests.post(f"{self.base}/images/generations", headers=headers, json=common, timeout=600)
        if resp.status_code >= 400:
            raise RuntimeError(f"gpt-image-1 {resp.status_code}: {resp.text[:500]}")
        return [_decode(item["b64_json"]) for item in resp.json()["data"]]


class ComfyUIProvider(Provider):
    name = "comfyui"
    PROMPT_TOKEN = "__PROMPT__"

    def __init__(self, base_url: str | None = None, workflow: str | None = None):
        self.base_url = (base_url or os.environ.get("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
        wf = workflow or os.environ.get("COMFYUI_WORKFLOW")
        if not wf:
            raise RuntimeError("缺少 COMFYUI_WORKFLOW（指向导出的 API 格式 workflow JSON）")
        self.workflow = json.loads(Path(wf).read_text(encoding="utf-8"))
        self.client_id = str(uuid.uuid4())

    def _inject(self, prompt: str, seed: int | None) -> dict:
        wf = json.loads(json.dumps(self.workflow))
        for node in wf.values():
            inputs = node.get("inputs", {})
            if inputs.get("text") == self.PROMPT_TOKEN:
                inputs["text"] = prompt
            if seed is not None and "seed" in inputs:
                inputs["seed"] = seed
        return wf

    def generate(self, prompt, *, negative="", reference=None, size=(1024, 1024), n=1, seed=None):
        if reference:
            raise NotImplementedError("ComfyUI 参考图需要 workflow 自带 LoadImage 节点")
        images: list[Image.Image] = []
        for i in range(n):
            wf = self._inject(prompt, None if seed is None else seed + i)
            resp = requests.post(
                f"{self.base_url}/prompt",
                json={"prompt": wf, "client_id": self.client_id},
                timeout=60,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"ComfyUI {resp.status_code}: {resp.text[:500]}")
            prompt_id = resp.json()["prompt_id"]
            images.append(self._wait(prompt_id))
        return images

    def _wait(self, prompt_id: str, timeout: float = 600) -> Image.Image:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hist = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=30).json()
            if prompt_id in hist:
                outputs = hist[prompt_id]["outputs"]
                for node in outputs.values():
                    for img in node.get("images", []):
                        params = {"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img["type"]}
                        raw = requests.get(f"{self.base_url}/view", params=params, timeout=60).content
                        return Image.open(io.BytesIO(raw)).convert("RGBA")
                raise RuntimeError(f"ComfyUI 任务 {prompt_id} 没有图片输出")
            time.sleep(1.5)
        raise TimeoutError(f"ComfyUI 任务 {prompt_id} 超时")


REGISTRY: dict[str, type[Provider]] = {
    SeedreamProvider.name: SeedreamProvider,
    GptImageProvider.name: GptImageProvider,
    ComfyUIProvider.name: ComfyUIProvider,
}


def get_provider(name: str, **kwargs) -> Provider:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise SystemExit(f"未知 provider: {name}（可用: {known}）")
    return REGISTRY[name](**kwargs)
