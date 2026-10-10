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
    def __init__(self) -> None:
        self._lock = threading.Lock()          # 防止后台循环与手动触发并发生图
        self._stop = threading.Event()
        self.state: dict = {"log": []}
        self._load_state()
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

            # 3. 标签化命名
            tags = naming.compose_tags(info, now, cfg["naming"])
            base_name = config.base_stem(cfg)
            base_path = config.active_base_path(cfg)
            stem = naming.compose_stem(base_name, tags)
            self.log(f"标签: {tags['weather']} | {tags['hours']} | {tags['temp']} | "
                     f"{tags['solarterm']}({tags['solarterm_cn']}) -> {stem}")

            # 4. 懒加载：两层壁纸库 wallpapers/{基准图前缀}/，缓存命中直接用
            wdir = config.wallpaper_dir(base_name)
            wdir.mkdir(parents=True, exist_ok=True)
            target = naming.find_cached(wdir, stem)
            cached = target is not None
            if force_regenerate and cached:
                target.unlink()
                target = None
                cached = False
            if target is None:
                prompt = naming.fill_prompt(
                    cfg["generator"].get("prompt") or "", tags, info["city"], base_name,
                    lang=str((cfg.get("ui") or {}).get("language") or "en"))
                data, ext = generate.generate_image(
                    cfg["generator"], prompt, base_path,
                    proxy=region_net_proxy(cfg))
                target = wdir / f"{stem}.{ext}"
                target.write_bytes(data)
                self.log(f"AI 生图完成 -> {base_name}/{target.name} "
                         f"({'基准图模式' if base_path else '文生图模式'}, "
                         f"{'降级直用基准图' if not cfg['generator'].get('api_key') else 'API生成'})")

            # 5. 切换壁纸(可指定显示器)
            should_apply = cfg["wallpaper"].get("apply", True) if apply is None else apply
            displays = cfg["wallpaper"].get("displays", "all")
            applied = False
            if should_apply:
                wallpaper.set_wallpaper(target, displays=displays)
                applied = True
                self.log(f"壁纸已切换: {base_name}/{target.name} "
                         f"(显示器: {displays if displays != 'all' else 'all'})")

            self.state.update({
                "last_run": dt.datetime.now().isoformat(timespec="seconds"),
                "last_weather": dict(info),
                "last_tags": tags,
                "last_stem": stem,
                "last_target": str(target),
                "last_cached": cached,
                "last_applied": applied,
                "last_error": None,
                "base_name": base_name,
                "has_base_image": base_path is not None,
            })
            self.save_state()
            return {
                "ok": True, "region": reg, "weather": dict(info), "tags": tags,
                "stem": stem, "file": str(target), "cached": cached, "applied": applied,
            }

    def run_guarded(self, apply: bool | None = None) -> dict | None:
        try:
            return self.run_once(apply=apply)
        except Exception as e:  # noqa: BLE001 - 后台循环不能崩
            err = f"{e}"
            self.log(f"执行失败: {err}")
            traceback.print_exc()
            self.state["last_error"] = err
            self.save_state()
            return None

    # ---------- 后台调度 ----------

    def start_scheduler(self) -> threading.Thread:
        def loop() -> None:
            self.log("调度器已启动")
            while not self._stop.is_set():
                self.run_guarded()
                minutes = 30
                try:
                    minutes = max(1, int(config.load_config().get("refresh_minutes") or 30))
                except Exception:  # noqa: BLE001
                    pass
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
            "state": {k: v for k, v in self.state.items() if k != "log"},
            "log": self.state.get("log", [])[-50:],
        }


def region_net_proxy(cfg: dict) -> str:
    return str((cfg.get("network") or {}).get("proxy") or "").strip()


def _version() -> str:
    from . import __version__
    return __version__


def _platform() -> str:
    import sys
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "Linux")
