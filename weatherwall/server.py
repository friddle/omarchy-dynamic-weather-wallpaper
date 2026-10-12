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
  GET  /api/ref-images        参考图列表(角色/风格样例, 随生图上传)
  GET  /api/ref-image-file?name=...  取参考图文件(预览用)
  POST /api/ref-image         上传参考图 {name, data_b64}
  POST /api/ref-image-delete  删除参考图 {name}
  POST /api/prompt-cfg        prompt 模板管理 {action: add/save/select/delete, name, template}
  POST /api/install-ffmpeg    后台安装 ffmpeg(平台包管理器)
  GET  /api/calendar-events   已导入的日历日程
  POST /api/calendar-import   导入 macOS 系统日历(触发权限申请, 仅 macOS)
"""

import base64
import datetime as dt
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, naming, region, wallpaper
from .app import App
from . import net
from .weather import china_cities, fetch_weather, find_china_city, US_CITIES

# 无需令牌的端点: 设置页本身(含拆分出的静态资源)、顶栏挂件用的状态接口、城市静态表和图片预览。
# 其余(含 API 明文的 /api/config、各种变更操作)一律要求 X-Token 请求头,
# 防止同机其他账户未授权读取密钥或改动配置。
_OPEN_PATHS = {"/", "/index.html", "/style.css", "/app.js", "/i18n.js",
               "/api/status", "/api/cities",
               "/api/wallpaper-file", "/api/base-image-file", "/api/ref-image-file"}

# 设置页静态资源及 MIME(按扩展名)
_WEB_STATIC = {"/style.css": "text/css", "/app.js": "application/javascript",
               "/i18n.js": "application/javascript"}

_TOKEN = ""
_FFMPEG_INSTALL = {"running": False, "error": None}   # 后台安装 ffmpeg 的状态


def _auth_token() -> str:
    """本地访问令牌: 首次启动生成, 0600 保存; 设置页由服务端注入, 无需手工配置。"""
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    p = config.config_dir() / "token"
    try:
        t = p.read_text(encoding="utf-8").strip()
        if t:
            _TOKEN = t
            return _TOKEN
    except OSError:
        pass
    _TOKEN = secrets.token_urlsafe(24)
    try:
        config.ensure_dirs()
        p.write_text(_TOKEN + "\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(p, 0o600)
    except OSError:
        pass
    return _TOKEN


def _index_html() -> bytes:
    """返回注入了令牌的设置页(注入到首个 script 标签之前, 页面 JS 自动携带)。"""
    data = web_index_path().read_bytes()
    inject = (b"<script>var APITOKEN=" + json.dumps(_auth_token()).encode() + b";</script>")
    i = data.find(b"<script")   # 兼容 <script src=...> 外链形式
    return data[:i] + inject + data[i:] if i >= 0 else data + inject


def web_index_path() -> Path:
    """设置页静态文件；兼容 PyInstaller 冻结(--onefile 时在 _MEIPASS)。"""
    p = Path(__file__).parent / "web" / "index.html"
    if p.exists():
        return p
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "weatherwall" / "web" / "index.html"
        if frozen.exists():
            return frozen
    return p


def web_static_path(name: str) -> Path:
    """设置页静态资源(style.css / app.js / i18n.js), 冻结环境同样回落 _MEIPASS。"""
    p = Path(__file__).parent / "web" / name
    if p.exists():
        return p
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "weatherwall" / "web" / name
        if frozen.exists():
            return frozen
    return p

SAFE_NAME = re.compile(r"^[^/\\]+$")


def _safe_file(root: Path, name: str) -> Path | None:
    """支持一层子目录(两层壁纸库 wallpapers/{base}/{file}.jpg)，防目录穿越。
    Windows 反斜杠统一为正斜杠(图库接口全程使用 posix 风格相对路径)。"""
    name = (name or "").replace("\\", "/")
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


def _unique_name(root: Path, name: str) -> str:
    """同名文件自动追加序号: xxx.jpg / xxx_2.jpg ..."""
    p = Path(name)
    stem, suffix = p.stem, p.suffix
    candidate = name
    i = 2
    while (root / candidate).exists():
        candidate = f"{stem}_{i}{suffix}"
        i += 1
    return candidate


def _grouped_wallpapers() -> list[dict]:
    """两层壁纸库: [{base, items:[...]}, ...] 按基准图前缀分组。
    rel 统一 posix 风格(Windows 下 relative_to 产生反斜杠会导致分组/预览失效)。"""
    root = config.cache_dir()
    groups: dict[str, list] = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in config.WALLPAPER_EXTS:
                continue
            rel = p.relative_to(root).as_posix()
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

        def _file(self, src, mime: str) -> None:
            data = src.read_bytes() if isinstance(src, Path) else bytes(src)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            tok = self.headers.get("X-Token", "")
            want = _auth_token()
            return bool(want) and hmac.compare_digest(tok, want)

        # ---- GET ----

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            try:
                if url.path not in _OPEN_PATHS and not self._authed():
                    return self._json({"ok": False, "error": "unauthorized"}, 401)
                if url.path in ("/", "/index.html"):
                    self._file(_index_html(), "text/html; charset=utf-8")
                elif url.path in _WEB_STATIC:
                    p = web_static_path(url.path.lstrip("/"))
                    if not p.exists():
                        return self._json({"ok": False, "error": "not found"}, 404)
                    self._file(p, _WEB_STATIC[url.path] + "; charset=utf-8")
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
                elif url.path == "/api/gen-models":
                    # 拉取生图接口的模型列表(/models), 供设置页下拉
                    cfg = config.load_config()
                    g = cfg["generator"]
                    base = (g.get("base_url") or "").rstrip("/")
                    if not base:
                        return self._json({"ok": False, "error": "base_url 未配置"}, 400)
                    key = (g.get("api_key") or "").strip()
                    headers = {"Authorization": f"Bearer {key}"} if key else {}
                    try:
                        data = net.http_json(base + "/models", timeout=15, headers=headers)
                        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    except Exception as e:  # noqa: BLE001
                        return self._json({"ok": False, "error": str(e)[:200]})
                    self._json({"ok": True, "models": ids})

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
                elif url.path == "/api/ref-images":
                    d = config.ref_images_dir()
                    items = sorted((p for p in d.glob("*")
                                    if p.is_file() and p.suffix.lower() in config.WALLPAPER_EXTS),
                                   key=lambda p: p.name) if d.exists() else []
                    self._json({"ok": True, "items": [_image_entry(p) for p in items]})
                elif url.path == "/api/ref-image-file":
                    p = _safe_file(config.ref_images_dir(), (qs.get("name") or [""])[0])
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    self._file(p, "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else
                               ("image/png" if p.suffix.lower() == ".png" else "image/webp"))
                elif url.path == "/api/calendar-events":
                    from . import widget as _wg
                    ev = _wg.load_events()
                    self._json({"ok": True, "events": ev,
                                "count": sum(len(v) for v in ev.values())})
                else:
                    self._json({"ok": False, "error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)}, 500)

        # ---- POST ----

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            body = self._body()
            try:
                if not self._authed():
                    return self._json({"ok": False, "error": "unauthorized"}, 401)
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
                    from .app import ref_image_paths
                    refs = ref_image_paths()
                    prompt = naming.fill_prompt(
                        config.active_prompt_template(cfg), tags, info["city"],
                        config.base_stem(cfg),
                        lang=str((cfg.get("ui") or {}).get("language") or "en"),
                        ref_names=[p.stem for p in refs])
                    self._json({"ok": True, "region": reg, "weather": dict(info),
                                "tags": tags, "stem": stem, "cached": cached is not None,
                                "prompt": prompt})

                elif url.path in ("/api/refresh", "/api/force-generate"):
                    cfg_g = config.load_config()["generator"]
                    if not (cfg_g.get("api_key") or "").strip():
                        return self._json({
                            "ok": False,
                            "error": "尚未配置生图 API Key — 请在 Base & AI 标签页填写后再刷新"}, 400)
                    apply_ = bool(body.get("apply", True))
                    force = url.path == "/api/force-generate" or bool(body.get("force"))
                    result = {}

                    def work():
                        result["res"] = app.run_guarded(apply=apply_, force=force)

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
                    target = p
                    wcfg = config.load_config().get("widget") or {}
                    if wcfg.get("enabled"):
                        # 图库点击也走挂件合成(字段值用最近一轮的天气/标签)
                        try:
                            from . import widget as infowidget
                            info = dict(app.state.get("last_weather") or {})
                            tags = dict(app.state.get("last_tags") or {})
                            if info and tags:
                                wdata, wext = infowidget.compose(
                                    p.read_bytes(), wcfg, info, tags, dt.datetime.now(),
                                    lang=str((config.load_config().get("ui") or {}).get("language") or "en"))
                                out = config.applied_dir() / f"{p.stem}.{wext}"
                                out.parent.mkdir(parents=True, exist_ok=True)
                                out.write_bytes(wdata)
                                target = out
                        except Exception as e:  # noqa: BLE001 - 挂件失败不影响壁纸
                            app.log(f"挂件合成失败，使用原图: {e}")
                    wallpaper.set_wallpaper(target, displays=displays)
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
                    suffix = Path(name).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                        suffix = ".jpg"
                    safe = _unique_name(config.base_images_dir(),
                                        config.normalize_stem(name) + suffix)
                    config.ensure_dirs()
                    (config.base_images_dir() / safe).write_bytes(data)
                    cfg = config.load_config()
                    cfg["base_image"] = safe
                    config.save_config(cfg)
                    app.log(f"上传基准图: {safe} (已设为生效)")
                    self._json({"ok": True, "name": safe, "stem": config.base_stem(cfg)})

                elif url.path == "/api/base-image-rename":
                    name = str(body.get("name") or "")
                    new_stem = config.normalize_stem(str(body.get("new_name") or ""))
                    p = _safe_file(config.base_images_dir(), name)
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    if not new_stem:
                        return self._json({"ok": False, "error": "新名称无效"}, 400)
                    new_name = _unique_name(config.base_images_dir(), new_stem + p.suffix.lower())
                    old_stem = config.normalize_stem(p.name)
                    p.rename(config.base_images_dir() / new_name)
                    # 同步迁移该基准图的壁纸缓存目录(两层壁纸库按前缀分目录)
                    old_dir = config.wallpaper_dir(old_stem)
                    new_dir = config.wallpaper_dir(config.normalize_stem(new_name))
                    if old_dir.exists() and old_dir != new_dir and not new_dir.exists():
                        old_dir.rename(new_dir)
                    cfg = config.load_config()
                    if cfg.get("base_image") == name:
                        cfg["base_image"] = new_name
                        config.save_config(cfg)
                    app.log(f"基准图重命名: {name} -> {new_name}")
                    self._json({"ok": True, "name": new_name,
                                "stem": config.normalize_stem(new_name)})

                elif url.path == "/api/base-image-generate":
                    # 弹窗自动生成基准图(文生图, 需已配置 API Key)
                    import datetime as _dt

                    from . import generate as _gen
                    prompt = str(body.get("prompt") or "").strip() or config.DEFAULT_BASE_PROMPT
                    cfg = config.load_config()
                    if not (cfg["generator"].get("api_key") or "").strip():
                        return self._json({"ok": False,
                                           "error": "尚未配置生图 API Key，请先在 Base & AI 标签页填写"}, 400)
                    stem = config.normalize_stem(str(body.get("name") or "")) \
                        or f"base_{_dt.datetime.now().strftime('%m%d_%H%M%S')}"
                    data, ext = _gen.generate_image(
                        cfg["generator"], prompt, None,
                        proxy=str((cfg.get("network") or {}).get("proxy") or ""))
                    safe = _unique_name(config.base_images_dir(), f"{stem}.{ext}")
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

                elif url.path == "/api/ref-image":
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
                    suffix = Path(name).suffix.lower()
                    if suffix not in config.WALLPAPER_EXTS:
                        suffix = ".png"
                    safe = _unique_name(config.ref_images_dir(),
                                        config.normalize_stem(name) + suffix)
                    config.ensure_dirs()
                    config.ref_images_dir().mkdir(parents=True, exist_ok=True)
                    (config.ref_images_dir() / safe).write_bytes(data)
                    app.log(f"上传参考图: {safe}")
                    self._json({"ok": True, "name": safe})

                elif url.path == "/api/ref-image-delete":
                    name = str(body.get("name") or "")
                    p = _safe_file(config.ref_images_dir(), name)
                    if not p:
                        return self._json({"ok": False, "error": "文件不存在"}, 404)
                    p.unlink()
                    app.log(f"删除参考图: {name}")
                    self._json({"ok": True})

                elif url.path == "/api/prompt-cfg":
                    action = str(body.get("action") or "")
                    name = str(body.get("name") or "").strip()
                    template = str(body.get("template") or "")
                    cfg = config.load_config()
                    prompts = cfg["generator"].setdefault("prompts", [])
                    if not prompts:
                        prompts.append({"name": "default", "template": config.DEFAULT_PROMPT})
                    active = cfg["generator"].get("active_prompt") or prompts[0]["name"]

                    def sync_prompt():
                        # 兼容字段: 与生效模板保持同步
                        for p in prompts:
                            if p["name"] == cfg["generator"].get("active_prompt"):
                                cfg["generator"]["prompt"] = p["template"]
                                return

                    if action == "add":
                        norm = config.normalize_stem(name) or f"prompt_{len(prompts) + 1}"
                        if any(p["name"] == norm for p in prompts):
                            return self._json({"ok": False, "error": f"模板名已存在: {norm}"}, 400)
                        prompts.append({"name": norm,
                                        "template": template or config.DEFAULT_PROMPT})
                        cfg["generator"]["active_prompt"] = norm
                        app.log(f"新增 prompt 模板: {norm}")
                    elif action == "save":
                        p = next((p for p in prompts if p["name"] == name), None)
                        if not p:
                            return self._json({"ok": False, "error": "模板不存在"}, 404)
                        if not template.strip():
                            return self._json({"ok": False, "error": "模板内容为空"}, 400)
                        p["template"] = template
                        app.log(f"保存 prompt 模板: {name}")
                    elif action == "select":
                        if not any(p["name"] == name for p in prompts):
                            return self._json({"ok": False, "error": "模板不存在"}, 404)
                        cfg["generator"]["active_prompt"] = name
                        app.log(f"切换生效 prompt 模板: {name}")
                    elif action == "delete":
                        if len(prompts) <= 1:
                            return self._json({"ok": False, "error": "至少保留一个模板"}, 400)
                        if not any(p["name"] == name for p in prompts):
                            return self._json({"ok": False, "error": "模板不存在"}, 404)
                        prompts[:] = [p for p in prompts if p["name"] != name]
                        if active == name:
                            cfg["generator"]["active_prompt"] = prompts[0]["name"]
                        app.log(f"删除 prompt 模板: {name}")
                    else:
                        return self._json({"ok": False, "error": "action 无效"}, 400)
                    sync_prompt()
                    config.save_config(cfg)
                    self._json({"ok": True, "prompts": prompts,
                                "active": cfg["generator"]["active_prompt"]})

                elif url.path == "/api/install-ffmpeg":
                    from . import widget as _wg
                    if _FFMPEG_INSTALL["running"]:
                        return self._json({"ok": True, "running": True})
                    cmd = _wg.install_command()
                    if not cmd:
                        return self._json({
                            "ok": False,
                            "error": "未找到可用的包管理器(brew/winget/choco/scoop/apt/dnf/pacman), 请手动安装 ffmpeg"},
                            400)

                    def install_work():
                        _FFMPEG_INSTALL["running"] = True
                        _FFMPEG_INSTALL["error"] = None
                        try:
                            app.log(f"开始安装 ffmpeg: {' '.join(cmd)} (可能需要几分钟)")
                            r = subprocess.run(cmd, capture_output=True, timeout=1800)
                            if r.returncode != 0:
                                tail = r.stderr.decode("utf-8", "replace").strip()[-300:]
                                _FFMPEG_INSTALL["error"] = tail
                                app.log(f"ffmpeg 安装失败: {tail}")
                            else:
                                _wg._DRAWTEXT_CACHE.clear()
                                if _wg.available():
                                    app.log("ffmpeg 安装完成, 挂件功能已可用")
                                else:
                                    app.log("安装命令执行完成, 但未检测到可用 ffmpeg, 可能需要重启服务")
                        except Exception as e:  # noqa: BLE001
                            _FFMPEG_INSTALL["error"] = str(e)
                            app.log(f"ffmpeg 安装失败: {e}")
                        finally:
                            _FFMPEG_INSTALL["running"] = False

                    threading.Thread(target=install_work, daemon=True,
                                     name="ffmpeg-installer").start()
                    self._json({"ok": True, "running": True})

                elif url.path == "/api/calendar-import":
                    from . import widget as _wg
                    if sys.platform != "darwin":
                        return self._json({"ok": False, "error": "仅 macOS 支持导入系统日历"}, 400)
                    events = _wg.import_macos_calendar()
                    count = sum(len(v) for v in events.values())
                    app.log(f"macOS 日历导入完成: {len(events)} 天 / {count} 条日程")
                    self._json({"ok": True, "days": len(events), "count": count})
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
