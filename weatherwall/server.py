"""本地设置后台：HTTP API + 静态设置页，仅绑定 127.0.0.1。

API:
  GET  /                      设置页
  GET  /api/status            运行状态/最近日志
  GET  /api/config            读取配置
  POST /api/config            保存配置(JSON)
  POST /api/detect-region     强制重新探测区域
  POST /api/test-weather      试拉天气并预览目标文件名(不生图不切壁纸)
  POST /api/refresh           立即执行一轮(后台线程, apply 可选)
  POST /api/force-generate    删缓存强制重新生图并执行一轮
  GET  /api/wallpapers        已生成的壁纸列表
  GET  /api/wallpaper-file?name=...  取壁纸文件(预览用)
  POST /api/apply             应用指定壁纸 {file}
  GET  /api/base-images       基准图列表
  GET  /api/base-image-file?name=... 取基准图文件(预览用)
  POST /api/base-image        上传基准图 {name, data_b64}
  POST /api/base-image-select 选择生效基准图 {name}
  POST /api/base-image-delete 删除基准图 {name}
"""

import base64
import datetime as dt
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, naming, region, wallpaper
from .app import App
from . import net
from .weather import china_cities, fetch_weather, find_china_city, US_CITIES

SAFE_NAME = re.compile(r"^[^/\\]+$")


def _safe_file(root: Path, name: str) -> Path | None:
    """支持一层子目录(两层壁纸库 wallpapers/{base}/{file}.jpg)，防目录穿越。"""
    if not name or ".." in name:
        return None
    parts = name.split("/")
    if len(parts) > 2 or not all(SAFE_NAME.match(p) for p in parts):
        return None
    p = root.joinpath(*parts).resolve()
    root_r = root.resolve()
    if p.parent != root_r and p.parent.parent != root_r:
        return None
    return p if p.exists() else None


def _image_entry(p: Path, rel: str | None = None) -> dict:
    return {"name": rel or p.name, "size": p.stat().st_size,
            "mtime": int(p.stat().st_mtime)}


def _grouped_wallpapers() -> list[dict]:
    """两层壁纸库: [{base, items:[...]}, ...] 按基准图前缀分组。"""
    root = config.cache_dir()
    groups: dict[str, list] = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in config.WALLPAPER_EXTS:
                continue
            rel = str(p.relative_to(root))
            base = rel.split("/", 1)[0] if "/" in rel else "(misc)"
            groups.setdefault(base, []).append(_image_entry(p, rel))
    out = []
    for base, items in groups.items():
        items.sort(key=lambda x: x["mtime"], reverse=True)
        out.append({"base": base, "count": len(items), "latest": items[0]["mtime"] if items else 0,
                    "items": items})
    out.sort(key=lambda g: g["latest"], reverse=True)
    return out


def make_handler(app: App) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "weatherwall/0.1"

        # ---- 基础 ----

        def log_message(self, fmt, *args):  # 静默访问日志
            pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}

        def _file(self, path: Path, mime: str) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        # ---- GET ----

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    page = Path(__file__).parent / "web" / "index.html"
                    self._file(page, "text/html; charset=utf-8")
                elif url.path == "/api/cities":
                    self._json({"ok": True, "china": china_cities(), "us": US_CITIES})
                elif url.path == "/api/status":
                    self._json(app.status())
                elif url.path == "/api/config":
                    cfg = config.load_config()
                    self._json({"ok": True, "config": cfg,
                                "default_base_prompt": config.DEFAULT_BASE_PROMPT})
                elif url.path == "/api/wallpapers":
                    self._json({"ok": True, "groups": _grouped_wallpapers()})
                elif url.path == "/api/displays":
                    self._json({"ok": True,
                                "displays": wallpaper.list_displays(),
                                "selected": config.load_config().get("wallpaper", {})
                                            .get("displays", "all")})
                elif url.path == "/api/wallpaper-file":
                    p = _safe_file(config.cache_dir(), (qs.get("name") or [""])[0])
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    self._file(p, "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else
                               ("image/png" if p.suffix.lower() == ".png" else "image/webp"))
                elif url.path == "/api/base-images":
                    files = sorted(config.base_images_dir().glob("*"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)
                    cfg = config.load_config()
                    self._json({"ok": True, "active": cfg.get("base_image", ""),
                                "items": [_image_entry(p) for p in files
                                          if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]})
                elif url.path == "/api/base-image-file":
                    p = _safe_file(config.base_images_dir(), (qs.get("name") or [""])[0])
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    self._file(p, "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else
                               ("image/png" if p.suffix.lower() == ".png" else "image/webp"))
                else:
                    self._json({"ok": False, "error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)}, 500)

        # ---- POST ----

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            body = self._body()
            try:
                if url.path == "/api/config":
                    cfg = config.load_config()
                    incoming = body.get("config")
                    if not isinstance(incoming, dict):
                        return self._json({"ok": False, "error": "config 字段缺失"}, 400)

                    def merge(dst, src):
                        for k, v in src.items():
                            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                                merge(dst[k], v)
                            else:
                                dst[k] = v

                    merge(cfg, incoming)
                    config.save_config(cfg)
                    app.log("配置已更新")
                    self._json({"ok": True})

                elif url.path == "/api/detect-region":
                    cfg = config.load_config()
                    r = region.probe_region(cfg, force=True)
                    self._json({"ok": True, "region": r,
                                "cached": region.region_cache()})

                elif url.path == "/api/locate":
                    # IP 定位必须直连(不走代理, 否则定位到代理出口)
                    data = net.http_json(
                        "http://ip-api.com/json/?fields=status,country,countryCode,city,lat,lon",
                        timeout=8, proxy="", direct=True)
                    if data.get("status") != "success":
                        return self._json({"ok": False, "error": f"locate failed: {data}"}, 502)
                    city = str(data.get("city") or "")
                    matched = find_china_city(city) if str(data.get("countryCode")) == "CN" else None
                    self._json({
                        "ok": True,
                        "country": data.get("country"),
                        "country_code": data.get("countryCode"),
                        "city": city,
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "china_city": matched,   # 命中内置中国城市表则返回 {cn,en,code}
                    })

                elif url.path == "/api/test-weather":
                    cfg = config.load_config()
                    reg = region.resolve_region(cfg, force=bool(body.get("force")))
                    info = fetch_weather(cfg, reg)
                    now = dt.datetime.now()
                    tags = naming.compose_tags(info, now, cfg["naming"])
                    stem = naming.compose_stem(config.base_stem(cfg), tags)
                    cached = naming.find_cached(config.cache_dir(), stem)
                    prompt = naming.fill_prompt(cfg["generator"].get("prompt") or config.DEFAULT_PROMPT,
                                                tags, info["city"], config.base_stem(cfg),
                                                lang=str((cfg.get("ui") or {}).get("language") or "en"))
                    self._json({"ok": True, "region": reg, "weather": dict(info),
                                "tags": tags, "stem": stem, "cached": cached is not None,
                                "prompt": prompt})

                elif url.path in ("/api/refresh", "/api/force-generate"):
                    apply_ = bool(body.get("apply", True))
                    force = url.path == "/api/force-generate" or bool(body.get("force"))
                    result = {}

                    def work():
                        result["res"] = app.run_guarded(apply=apply_)

                    t = threading.Thread(target=work)
                    t.start()
                    t.join(timeout=float(body.get("wait_seconds", 8)))
                    if t.is_alive():
                        self._json({"ok": True, "queued": True,
                                    "msg": "任务仍在后台执行(生图较慢)，稍后查看状态"})
                    else:
                        res = result.get("res")
                        self._json({"ok": bool(res), "queued": False,
                                    "result": res, "error": None if res else app.state.get("last_error")})
                    return

                elif url.path == "/api/apply":
                    name = str(body.get("file") or "")
                    p = _safe_file(config.cache_dir(), name)
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    displays = config.load_config().get("wallpaper", {}).get("displays", "all")
                    wallpaper.set_wallpaper(p, displays=displays)
                    app.log(f"手动应用壁纸: {name} (显示器: {displays})")
                    self._json({"ok": True})

                elif url.path == "/api/base-image":
                    name = str(body.get("name") or "").strip()
                    data_b64 = str(body.get("data_b64") or "")
                    if not name or not SAFE_NAME.match(name):
                        return self._json({"ok": False, "error": "文件名非法"}, 400)
                    try:
                        data = base64.b64decode(data_b64)
                    except Exception:
                        return self._json({"ok": False, "error": "data_b64 解码失败"}, 400)
                    if len(data) > 30 * 1024 * 1024:
                        return self._json({"ok": False, "error": "文件超过 30MB"}, 400)
                    stem = Path(name).stem
                    suffix = Path(name).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                        suffix = ".jpg"
                    safe = re.sub(r"[^\w\-. ]+", "_", stem) + suffix
                    config.ensure_dirs()
                    (config.base_images_dir() / safe).write_bytes(data)
                    cfg = config.load_config()
                    cfg["base_image"] = safe
                    config.save_config(cfg)
                    app.log(f"上传基准图: {safe} (已设为生效)")
                    self._json({"ok": True, "name": safe, "stem": config.base_stem(cfg)})

                elif url.path == "/api/base-image-generate":
                    # 弹窗自动生成基准图(文生图, 需已配置 API Key)
                    import datetime as _dt

                    from . import generate as _gen
                    prompt = str(body.get("prompt") or "").strip() or config.DEFAULT_BASE_PROMPT
                    cfg = config.load_config()
                    if not (cfg["generator"].get("api_key") or "").strip():
                        return self._json({"ok": False,
                                           "error": "尚未配置生图 API Key，请先在 Base & AI 标签页填写"}, 400)
                    stem = re.sub(r"[^\w\-.]+", "_", str(body.get("name") or "").strip()) \
                        or f"base_{_dt.datetime.now().strftime('%m%d_%H%M%S')}"
                    data, ext = _gen.generate_image(
                        cfg["generator"], prompt, None,
                        proxy=str((cfg.get("network") or {}).get("proxy") or ""))
                    safe = re.sub(r"[^\w\-. ]+", "_", stem) + "." + ext
                    config.ensure_dirs()
                    (config.base_images_dir() / safe).write_bytes(data)
                    cfg["base_image"] = safe
                    config.save_config(cfg)
                    app.log(f"自动生成基准图: {safe} (已设为生效)")
                    self._json({"ok": True, "name": safe, "stem": config.base_stem(cfg)})

                elif url.path == "/api/base-image-select":
                    name = str(body.get("name") or "")
                    p = _safe_file(config.base_images_dir(), name)
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    cfg = config.load_config()
                    cfg["base_image"] = name
                    config.save_config(cfg)
                    self._json({"ok": True, "stem": config.base_stem(cfg)})

                elif url.path == "/api/base-image-delete":
                    name = str(body.get("name") or "")
                    p = _safe_file(config.base_images_dir(), name)
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    cfg = config.load_config()
                    if cfg.get("base_image") == name:
                        cfg["base_image"] = ""
                        config.save_config(cfg)
                    p.unlink()
                    app.log(f"删除基准图: {name}")
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)}, 500)

    return Handler


def serve(app: App, host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    app.log(f"设置后台已启动: http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        httpd.server_close()
