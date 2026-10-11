"""主流程编排：读温度+时间+天气 -> 基准图+AI生成 -> 系统自动切换。

核心是懒加载：目标文件名由标签组合而成，缓存里已有就直接用，没有才调生图接口。
"""

import datetime as dt
import json
import threading
import time
import traceback
from pathlib import Path

from . import config, generate, naming, region, wallpaper
from .weather import fetch_weather


class App:
    def _heal_base_image(self, cfg: dict) -> tuple[dict, Path | None]:
        """基准图自愈: 未配置或文件丢失时, 自动回退到目录里最新一张。

        避免因为配置被清空而退化成无基准图的纯文生图。
        """
        base_path = config.active_base_path(cfg)
        if base_path is not None:
            return cfg, base_path
        avail = sorted(
            (p for p in config.base_images_dir().glob("*")
             if p.is_file() and p.suffix.lower() in config.WALLPAPER_EXTS),
            key=lambda p: p.stat().st_mtime, reverse=True)
        if avail:
            cfg["base_image"] = avail[0].name
            try:
                config.save_config(cfg)
            except OSError:
                pass
            self.log(f"基准图自愈: 生效图缺失/未配置, 已自动选用 {avail[0].name}")
            return cfg, avail[0]
        return cfg, None

    def __init__(self) -> None:
        self._lock = threading.Lock()          # 防止后台循环与手动触发并发生图
        self._stop = threading.Event()
        self.state: dict = {"log": []}
        self._load_state()
        try:
            if config.seed_if_empty():         # 首次运行: 内置基准图生效
                self.log("首次运行: 内置基准图 island.png 已生效")
        except OSError:
            pass
        try:
            moved = config.migrate_wallpaper_cache()  # 旧扁平结构 -> 按基准图分目录
            if moved:
                self.log(f"壁纸库迁移: {moved} 张已按基准图分目录")
        except OSError:
            pass

    # ---------- 状态与日志 ----------

    def _load_state(self) -> None:
        try:
            data = json.loads(config.state_file().read_text(encoding="utf-8"))
            self.state.update({k: v for k, v in data.items() if k != "log"})
            region.load_cached_region(self.state)
        except (OSError, json.JSONDecodeError):
            pass

    def save_state(self) -> None:
        config.ensure_dirs()
        rc = region.region_cache()
        if rc["region"]:
            self.state["region"] = rc["region"]
            self.state["region_ts"] = rc["ts"]
        try:
            config.state_file().write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def log(self, msg: str) -> None:
        line = f"[{dt.datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
        self.state.setdefault("log", []).append(line)
        self.state["log"] = self.state["log"][-200:]
        print(line, flush=True)

    # ---------- 主流程 ----------

    def run_once(self, apply: bool | None = None, force_regenerate: bool = False) -> dict:
        """执行一轮完整流程，返回结果摘要(供 CLI 与后台 API 复用)。"""
        with self._lock:
            cfg = config.load_config()
            config.ensure_dirs()
            now = dt.datetime.now()

            # 1. 区域(读温度+时间的通道选择)
            reg = region.resolve_region(cfg)
            self.log(f"区域: {reg} (配置={cfg['region']}, 代理={cfg['network'].get('proxy') or '无'})")

            # 2. 天气
            info = fetch_weather(cfg, reg)
            self.log(
                f"天气[{info['provider']}]: {info['city']} {info['desc']} "
                f"当前{info['temp_current']}℃ ({info['temp_min']}~{info['temp_max']}℃)"
            )

            # open-meteo 首次 geocode 成功后把坐标写回配置，之后离线也能跑
            if info.get("latitude") and not cfg["weather"].get("latitude"):
                cfg["weather"]["latitude"] = info["latitude"]
                cfg["weather"]["longitude"] = info["longitude"]
                try:
                    config.save_config(cfg)
                except OSError:
                    pass

            # 3. 标签化命名 + 基准图自愈(丢失/未配置时自动回退到最新一张, 避免退化成纯文生图)
            cfg, base_path = self._heal_base_image(cfg)
            tags = naming.compose_tags(info, now, cfg["naming"])
            base_name = config.base_stem(cfg)
            stem = naming.compose_stem(base_name, tags)
            self.log(f"标签: {tags['weather']} | {tags['hours']} | {tags['temp']} | "
                     f"{tags['solarterm']}({tags['solarterm_cn']}) -> {stem}")

            # 4. 懒加载：两层壁纸库 wallpapers/{基准图前缀}/，缓存命中直接用
            wdir = config.wallpaper_dir(base_name)
            wdir.mkdir(parents=True, exist_ok=True)
            target = naming.find_cached(wdir, stem)
            cached = target is not None
            gen_error: str | None = None
            if force_regenerate and cached:
                target.unlink()
                target = None
                cached = False
            if target is None:
                prompt = naming.fill_prompt(
                    cfg["generator"].get("prompt") or "", tags, info["city"], base_name,
                    lang=str((cfg.get("ui") or {}).get("language") or "en"))
                gen_cfg = dict(cfg["generator"])
                size = resolve_size(gen_cfg.get("size"), wallpaper.display_resolution())
                if size in _UNSUPPORTED:  # 进程内已知被拒: 直接取最近候选, 不再撞一次
                    size = nearest_sizes(size)[0]
                gen_cfg["size"] = size
                try:
                    try:
                        data, ext = generate.generate_image(
                            gen_cfg, prompt, base_path,
                            proxy=region_net_proxy(cfg))
                    except Exception as e:
                        # 目标尺寸不被接口支持(如 2560x1600): 由近到远换候选重试,
                        # fit_to 会把任意比例裁到屏幕尺寸, 视觉无损
                        if "size" not in str(e).lower():
                            raise
                        _UNSUPPORTED.add(str(gen_cfg.get("size")).lower())
                        cands = nearest_sizes(str(gen_cfg.get("size")))
                        last_err: Exception | None = e
                        for cand in cands[:2]:
                            self.log(f"尺寸 {gen_cfg.get('size')} 不被接口支持，改用 {cand} 重试")
                            gen_cfg["size"] = cand
                            try:
                                data, ext = generate.generate_image(
                                    gen_cfg, prompt, base_path,
                                    proxy=region_net_proxy(cfg))
                                break
                            except Exception as e2:
                                last_err = e2
                                if "size" not in str(e2).lower():
                                    raise
                                _UNSUPPORTED.add(cand)
                        else:
                            raise last_err if last_err else e
                except Exception as e:  # noqa: BLE001 - 生图失败不中断本轮: 有基准图则降级直用
                    if base_path is None:
                        raise
                    gen_error = str(e)
                    target = base_path
                    self.log(f"生图失败，本轮降级直用基准图 (不写入缓存): {gen_error}")
                else:
                    target = wdir / f"{stem}.{ext}"
                    target.write_bytes(data)
                    self.log(f"AI 生图完成 -> {base_name}/{target.name} "
                             f"({'基准图模式' if base_path else '文生图模式'}, "
                             f"{'降级直用基准图' if not cfg['generator'].get('api_key') else 'API生成'})")

            # 4.5 应用前图片操作: 分辨率适配显示器 + 可选信息挂件; 任一步失败回落原图
            apply_target = target
            wcfg = cfg.get("widget") or {}
            data = None
            try:
                from . import widget as infowidget
                res = wallpaper.display_resolution()
                if res:
                    try:
                        data, _ = infowidget.fit_to(target.read_bytes(), *res)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"分辨率适配失败，使用原图: {e}")
                if wcfg.get("enabled"):
                    src = data if data is not None else target.read_bytes()
                    try:
                        data, _ = infowidget.compose(
                            src, wcfg, info, tags, now,
                            lang=str((cfg.get("ui") or {}).get("language") or "en"))
                        self.log(f"挂件已合成 (样式: {wcfg.get('style') or 'glass'})")
                    except Exception as e:  # noqa: BLE001 - 保留已适配的图
                        self.log(f"挂件合成失败: {e}")
                if data is not None:
                    out = config.applied_dir() / f"{target.stem}.jpg"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
                    apply_target = out
            except Exception as e:  # noqa: BLE001 - 图片操作失败不影响壁纸
                self.log(f"图片操作跳过: {e}")

            # 5. 切换壁纸(可指定显示器)
            should_apply = cfg["wallpaper"].get("apply", True) if apply is None else apply
            displays = cfg["wallpaper"].get("displays", "all")
            applied = False
            if should_apply:
                wallpaper.set_wallpaper(apply_target, displays=displays)
                applied = True
                self.log(f"壁纸已切换: {base_name}/{apply_target.name} "
                         f"(显示器: {displays if displays != 'all' else 'all'})")

            self.state.update({
                "last_run": dt.datetime.now().isoformat(timespec="seconds"),
                "last_weather": dict(info),
                "last_tags": tags,
                "last_stem": stem,
                "last_target": str(apply_target),
                "last_cached": cached,
                "last_applied": applied,
                "last_gen_error": gen_error,
                "last_error": None,
                "base_name": base_name,
                "has_base_image": base_path is not None,
            })
            self.save_state()
            return {
                "ok": True, "region": reg, "weather": dict(info), "tags": tags,
                "stem": stem, "file": str(apply_target), "cached": cached, "applied": applied,
                "degraded": gen_error is not None,
                "widget": apply_target != target,
            }

    def run_guarded(self, apply: bool | None = None, force: bool = False) -> dict | None:
        try:
            return self.run_once(apply=apply, force_regenerate=force)
        except Exception as e:  # noqa: BLE001 - 后台循环不能崩
            err = f"{e}"
            self.log(f"执行失败: {err}")
            traceback.print_exc()
            self.state["last_error"] = err
            self.save_state()
            return None

    # ---------- 后台调度 ----------

    def _wait_network(self, timeout: float = 120.0) -> None:
        """开机后等网络就绪(最多 ~2 分钟)，避免第一轮注定失败的 DNS 竞态。"""
        end = time.time() + timeout
        while time.time() < end and not self._stop.is_set():
            try:
                if region.probe_region(config.load_config(), force=True):
                    self.log("网络已就绪")
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)
        self.log("等待网络超时，按当前状态继续")

    def start_scheduler(self) -> threading.Thread:
        def loop() -> None:
            self.log("调度器已启动")
            self._wait_network()
            while not self._stop.is_set():
                ok = self.run_guarded() is not None
                minutes = 30
                try:
                    minutes = max(1, int(config.load_config().get("refresh_minutes") or 30))
                except Exception:  # noqa: BLE001
                    pass
                err = str(self.state.get("last_error") or "")
                if not ok and is_network_error(err):
                    minutes = min(minutes, 2)  # 开机网络未就绪: 短间隔快速重试
                    self.log(f"网络未就绪，{minutes} 分钟后重试")
                end = time.time() + minutes * 60
                while time.time() < end and not self._stop.is_set():
                    time.sleep(min(5, max(0.1, end - time.time())))
        t = threading.Thread(target=loop, daemon=True, name="weatherwall-scheduler")
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        cfg = config.load_config()
        rc = region.region_cache()
        base = config.active_base_path(cfg)
        try:
            from . import widget as infowidget
            widget_ready = infowidget.available()
        except Exception:  # noqa: BLE001
            widget_ready = False
        return {
            "version": _version(),
            "platform": _platform(),
            "region_setting": cfg.get("region"),
            "region_detected": rc["region"] or self.state.get("region"),
            "proxy": cfg["network"].get("proxy", ""),
            "refresh_minutes": cfg.get("refresh_minutes"),
            "base_image": cfg.get("base_image", ""),
            "base_image_exists": base is not None,
            "has_api_key": bool(cfg["generator"].get("api_key")),
            "widget_ready": widget_ready,
            "state": {k: v for k, v in self.state.items() if k != "log"},
            "log": self.state.get("log", [])[-50:],
        }


def region_net_proxy(cfg: dict) -> str:
    return str((cfg.get("network") or {}).get("proxy") or "").strip()


def is_network_error(msg: str) -> bool:
    """仅匹配"网络未就绪"类错误(DNS/路由)，用于调度器快速重试；
    连接超时/被拒不算(可能是对端服务问题，按正常周期重试即可)。"""
    m = (msg or "").lower()
    return any(k in m for k in ("temporary failure in name resolution",
                                "name or service not known",
                                "network is unreachable"))


def resolve_size(size: str, display_res: tuple[int, int] | None) -> str:
    """size=auto(或空) 表示当前显示器分辨率；检测失败回落接口默认(auto)。"""
    s = (size or "auto").strip().lower()
    if s == "auto":
        return f"{display_res[0]}x{display_res[1]}" if display_res else "auto"
    return (size or "auto").strip()


# 常见支持尺寸(主流生图 API 的档位 + 常见显示器档位), 供"最近尺寸"回落
SIZE_LADDER = ["3840x2160", "2560x1440", "1920x1080",
               "1536x1024", "1024x1536", "1024x1024"]
_UNSUPPORTED: set[str] = set()  # 进程内记住被接口拒绝的尺寸


def _parse_wh(s: str) -> tuple[int, int] | None:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None


def nearest_sizes(target: str) -> list[str]:
    """与目标尺寸最接近的候选, 由近到远: 先比宽高比, 再比像素面积。
    已知被拒(_UNSUPPORTED)与目标本身被剔除; 目标无法解析时给通用横版。"""
    twh = _parse_wh(target)
    if not twh:
        return ["1536x1024"]
    tw, th = twh

    def dist(s: str) -> tuple[float, float]:
        w, h = _parse_wh(s) or (1, 1)
        return (abs(w / h - tw / th) / (tw / th),
                abs(w * h - tw * th) / (tw * th))

    cands = [s for s in SIZE_LADDER if s != target and s not in _UNSUPPORTED]
    return sorted(cands, key=dist)


def _version() -> str:
    from . import __version__
    return __version__


def _platform() -> str:
    import sys
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")
