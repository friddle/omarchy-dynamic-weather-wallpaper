"""AI 生图客户端：OpenAI 兼容 images API。

- 有基准图: POST {base_url}/images/edits (multipart, 图生图，保持基准图构图)
- 无基准图: POST {base_url}/images/generations (文生图)
- 未配置 api_key: 降级为直接使用基准图(或占位图)，保证主流程可跑通

返回 (图片bytes, 扩展名)。
"""

import base64
import json
import struct
import urllib.error
import uuid
import zlib

from . import net


class GenerateError(Exception):
    pass


def _multipart(fields: dict, file_field: str, filename: str, content: bytes,
               content_type: str) -> tuple[bytes, str]:
    boundary = "----weatherwall" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
            .encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _http(url: str, data: bytes, headers: dict, timeout: float, proxy: str) -> dict:
    try:
        return net.http_json(url, timeout=timeout, proxy=proxy, headers=headers, data=data)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise GenerateError(f"生图接口 HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise GenerateError(f"生图接口连接失败: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise GenerateError(f"生图接口返回非 JSON: {e}") from e


def _ext_of(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def _extract_image(payload: dict, timeout: float, proxy: str = "") -> bytes:
    items = payload.get("data") or []
    if not items:
        raise GenerateError(f"生图接口无 data: {json.dumps(payload, ensure_ascii=False)[:300]}")
    item = items[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return net.http_bytes(item["url"], timeout=timeout, proxy=proxy)
    raise GenerateError("生图接口既无 b64_json 也无 url")


def make_placeholder_png(size: tuple[int, int] = (1600, 1000)) -> bytes:
    """无基准图且无 key 时的纯色占位图(PNG, 仅标准库)。"""
    w, h = size
    rows = []
    for y in range(h):
        r = int(40 + 30 * y / h)
        g = int(60 + 40 * y / h)
        b = int(90 + 60 * y / h)
        rows.append(b"\x00" + bytes((r, g, b)) * w)
    raw = b"".join(rows)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return png


def generate_image(cfg_gen: dict, prompt: str, base_path=None, proxy: str = "") -> tuple[bytes, str]:
    """主入口：返回 (bytes, ext)。未配置 key 时走降级逻辑。"""
    api_key = (cfg_gen.get("api_key") or "").strip()
    base_url = (cfg_gen.get("base_url") or "").rstrip("/")
    timeout = float(cfg_gen.get("timeout_seconds") or 300)

    if not api_key:
        # 降级：无 key 直接用基准图当壁纸(或占位图)，方便先跑通流程
        if base_path is not None:
            data = base_path.read_bytes()
            return data, _ext_of(data)
        return make_placeholder_png(), "png"

    headers = {"Authorization": f"Bearer {api_key}"}
    model = cfg_gen.get("model") or "gpt-image-1"
    size = cfg_gen.get("size") or "auto"

    if base_path is not None:
        url = f"{base_url}/images/edits"
        fields = {"model": model, "prompt": prompt, "n": "1", "size": size}
        if model.startswith("gpt-image"):
            fields["output_format"] = "jpeg"   # gpt-image 系列支持直接出 jpeg
        else:
            fields["response_format"] = "b64_json"
        body, boundary = _multipart(fields, "image", base_path.name,
                                    base_path.read_bytes(),
                                    "image/jpeg" if base_path.suffix.lower() in (".jpg", ".jpeg") else "image/png")
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        url = f"{base_url}/images/generations"
        payload = {"model": model, "prompt": prompt, "n": 1, "size": size}
        if not model.startswith("gpt-image"):
            payload["response_format"] = "b64_json"
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    result = _http(url, body, headers, timeout, proxy)
    data = _extract_image(result, timeout, proxy)
    return data, _ext_of(data)


def prompt_preview(cfg_gen: dict, filled_prompt: str) -> dict:
    """调试用：展示将发送的请求形态。"""
    return {
        "url": (cfg_gen.get("base_url") or "").rstrip("/") + "/images/edits",
        "model": cfg_gen.get("model"),
        "size": cfg_gen.get("size"),
        "prompt": filled_prompt,
        "has_key": bool((cfg_gen.get("api_key") or "").strip()),
    }
