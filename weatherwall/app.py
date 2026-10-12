"""主流程编排：读温度+时间+天气 -> 基准图+AI生成 -> 系统自动切换。

核心是懒加载：目标文件名由标签组合而成，缓存里已有就直接用，没有才调生图接口。
"""

import datetime as dt
import hashlib
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
        self._precache_gate = threading.Lock()  # 预生成单飞(已在跑则跳过新触发)
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
            self.log(f"区域: {reg} (配置={cfg['region']}, "
                     f"代理={mask_proxy(cfg['network'].get('proxy')) or '无'})")

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
            stem = naming.compose_stem(base_name, tags, (cfg["naming"] or {}).get("cache_key"))
            self.log(f"标签: {tags['weather']} | {tags['daypart']} | {tags['temp']} | "
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
            if not cached:
                # AI 图重新生成过: 成品合成签名作废, 强制重走挂件合成
                self.state["compose_sig"] = None
            if target is None:
                refs = ref_image_paths()
                prompt = naming.fill_prompt(
                    config.active_prompt_template(cfg), tags, info["city"], base_name,
                    lang=str((cfg.get("ui") or {}).get("language") or "en"),
                    ref_names=[p.stem for p in refs])
                gen_cfg = dict(cfg["generator"])
                size = resolve_size(gen_cfg.get("size"), wallpaper.display_resolution())
                if size in _UNSUPPORTED:  # 进程内已知被拒: 直接取最近候选, 不再撞一次
                    size = nearest_sizes(size)[0]
                gen_cfg["size"] = size
                try:
                    try:
                        data, ext = generate.generate_image(
                            gen_cfg, prompt, base_path, refs,
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
                                    gen_cfg, prompt, base_path, refs,
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

            # 4.5 两段式第二段: 基于 AI 中间图做 分辨率适配 + 信息挂件 + 日历挂件,
            #     成品写 applied/。签名(日期+挂件配置+分辨率+语言)一致且成品存在则直接复用 ——
            #     日期变化只重合成日历, 不触发 AI 重新生图。
            apply_target = target
            wcfg = cfg.get("widget") or {}
            ccfg = cfg.get("widget_calendar") or {}
            lang = str((cfg.get("ui") or {}).get("language") or "en")
            res = wallpaper.display_resolution()
            sig = hashlib.md5(json.dumps({
                "date": now.strftime("%Y-%m-%d"),
                "res": res,
                "widget": wcfg if wcfg.get("enabled") else None,
                "calendar": ccfg if ccfg.get("enabled") else None,
                "lang": lang,
            }, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:10]
            out = config.applied_dir() / f"{target.stem}.jpg"
            data = None
            try:
                from . import widget as infowidget
                if out.exists() and self.state.get("compose_sig") == sig \
                        and self.state.get("compose_stem") == target.stem:
                    apply_target = out
                    self.log(f"成品缓存命中(合成签名一致): {out.name}")
                else:
                    if res:
                        try:
                            data, _ = infowidget.fit_to(target.read_bytes(), *res)
                        except Exception as e:  # noqa: BLE001
                            self.log(f"分辨率适配失败，使用原图: {e}")
                    if wcfg.get("enabled"):
                        src = data if data is not None else target.read_bytes()
                        try:
                            data, _ = infowidget.compose(
                                src, wcfg, info, tags, now, lang=lang)
                            self.log(f"挂件已合成 (样式: {wcfg.get('style') or 'glass'})")
                        except Exception as e:  # noqa: BLE001 - 保留已适配的图
                            self.log(f"挂件合成失败: {e}")
                    if ccfg.get("enabled"):
                        src = data if data is not None else target.read_bytes()
                        try:
                            data, _ = infowidget.compose_calendar(
                                src, ccfg, now, lang=lang)
                            self.log("日历挂件已合成")
                        except Exception as e:  # noqa: BLE001 - 保留已合成的图
                            self.log(f"日历挂件失败: {e}")
                    if data is not None:
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(data)
                        apply_target = out
                        self.state["compose_sig"] = sig
                        self.state["compose_stem"] = target.stem
                    else:
                        self.state["compose_sig"] = None
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

            # 6. 默认预生成: 提前备好接下来可能用到的壁纸(时段推进×天气轮转×节气窗口)
            pcfg = cfg.get("precache") or {}
            if pcfg.get("enabled", True):
                threading.Thread(target=self._precache_guarded,
                                 kwargs={"count": int(pcfg.get("count") or 12)},
                                 daemon=True, name="weatherwall-precache").start()

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

    # ---------- 预生成 ----------

    def _precache_guarded(self, count: int = 12) -> None:
        """单飞入口: 已有预生成在跑则直接跳过。"""
        if not self._precache_gate.acquire(blocking=False):
            return
        try:
            result = self.precache(count)
            self.log(f"预生成结束: 新生成 {result['generated']} 张, 已缓存跳过 {result['skipped']} 张")
        except Exception as e:  # noqa: BLE001 - 预生成失败不影响主流程
            self.log(f"预生成异常: {e}")
        finally:
            self._precache_gate.release()

    def precache(self, count: int = 12) -> dict:
        """预生成接下来可能用到的壁纸(时段推进×天气轮转×当前/下一节气), 写入壁纸库缓存。

        逐张短暂持有 self._lock, 与主流程生图互斥但不长期占锁; 不应用不切壁纸。
        """
        cfg = config.load_config()
        config.ensure_dirs()
        now = dt.datetime.now()
        info = dict(self.state.get("last_weather") or {})
        if not info:
            reg = region.resolve_region(cfg)
            info = fetch_weather(cfg, reg)
        cfg, base_path = self._heal_base_image(cfg)
        base_name = config.base_stem(cfg)
        wdir = config.wallpaper_dir(base_name)
        wdir.mkdir(parents=True, exist_ok=True)
        lang = str((cfg.get("ui") or {}).get("language") or "en")
        combos = naming.upcoming_combos(info, now, cfg["naming"], count)
        self.state["precache"] = {"running": True, "done": 0, "total": len(combos),
                                  "current": ""}
        self.save_state()
        generated = skipped = failed = 0
        try:
            for i, tags in enumerate(combos):
                if self._stop.is_set():
                    break
                stem = naming.compose_stem(base_name, tags, (cfg["naming"] or {}).get("cache_key"))
                self.state["precache"].update({"done": i, "current": stem})
                self.save_state()
                if naming.find_cached(wdir, stem):
                    skipped += 1
                    continue
                refs = ref_image_paths()
                prompt = naming.fill_prompt(
                    config.active_prompt_template(cfg), tags, str(info.get("city") or ""),
                    base_name, lang=lang, ref_names=[p.stem for p in refs])
                gen_cfg = dict(cfg["generator"])
                size = resolve_size(gen_cfg.get("size"), wallpaper.display_resolution())
                if size in _UNSUPPORTED:
                    size = nearest_sizes(size)[0]
                gen_cfg["size"] = size
                try:
                    with self._lock:
                        data, ext = generate.generate_image(
                            gen_cfg, prompt, base_path, refs,
                            proxy=region_net_proxy(cfg))
                except Exception as e:  # noqa: BLE001 - 单张失败继续后面的
                    failed += 1
                    self.log(f"预生成失败 {stem}: {e}")
                    continue
                (wdir / f"{stem}.{ext}").write_bytes(data)
                generated += 1
                self.log(f"预生成完成: {base_name}/{stem}.{ext} "
                         f"({tags['weather']}/{tags['daypart']}/{tags['solarterm_cn']})")
            return {"generated": generated, "skipped": skipped, "failed": failed}
        finally:
            self.state["precache"] = {"running": False, "done": len(combos),
                                      "total": len(combos)}
            self.save_state()

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

    def public_status(self) -> dict:
        """免鉴权 /api/status 的脱敏视图(顶栏挂件/未登录设置页使用)。

        排除一切可能携带凭据的字段: 代理配置(可能是 http://user:pass@host 形式)、
        日志与错误详情(可能记录带凭据的 URL)。完整视图走需令牌的 /api/status-full。
        """
        full = self.status()
        st = full.get("state") or {}
        return {
            "version": full.get("version"),
            "platform": full.get("platform"),
            "region_setting": full.get("region_setting"),
            "region_detected": full.get("region_detected"),
            "refresh_minutes": full.get("refresh_minutes"),
            "base_image": full.get("base_image", ""),
            "base_image_exists": full.get("base_image_exists", False),
            "has_api_key": full.get("has_api_key", False),
            "widget_ready": full.get("widget_ready", False),
            "ffmpeg_found": full.get("ffmpeg_found", False),
            "ffmpeg_drawtext": full.get("ffmpeg_drawtext", False),
            "ffmpeg_install_running": full.get("ffmpeg_install_running", False),
            "calendar_event_days": full.get("calendar_event_days", 0),
            "calendar_event_count": full.get("calendar_event_count", 0),
            "precache": full.get("precache", {}),
            "state": {k: st.get(k) for k in
                      ("last_run", "last_weather", "last_stem", "last_cached",
                       "last_applied", "has_base_image") if k in st},
        }

    def status(self) -> dict:
        cfg = config.load_config()
        rc = region.region_cache()
        base = config.active_base_path(cfg)
        try:
            from . import widget as infowidget
            widget_ready = infowidget.available()
            ffmpeg_found = infowidget.find_ffmpeg() is not None
            ffmpeg_drawtext = (infowidget.find_ffmpeg() is not None
                               and infowidget.ffmpeg_has_drawtext(infowidget.find_ffmpeg()))
            events = infowidget.load_events()
        except Exception:  # noqa: BLE001
            widget_ready = ffmpeg_found = ffmpeg_drawtext = False
            events = {}
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
            "ffmpeg_found": ffmpeg_found,
            "ffmpeg_drawtext": ffmpeg_drawtext,
            "ffmpeg_install_running": ffmpeg_install_running(),
            "ffmpeg_install_error": ffmpeg_install_error(),
            "calendar_event_days": len(events),
            "calendar_event_count": sum(len(v) for v in events.values()),
            "precache": dict(self.state.get("precache") or {}),
            "state": {k: v for k, v in self.state.items() if k != "log"},
            "log": self.state.get("log", [])[-50:],
        }


def region_net_proxy(cfg: dict) -> str:
    return str((cfg.get("network") or {}).get("proxy") or "").strip()


def mask_proxy(url: str) -> str:
    """日志用: 抹掉代理 URL 里的 userinfo(http://user:pass@host:port -> http://***@host:port)。"""
    import re
    return re.sub(r"(//)([^/@:]+):([^/@]+)@", r"\1***:***@", url or "")


def ref_image_paths(limit: int = 4) -> list[Path]:
    """随生图上传的参考图(按文件名排序, 截上限): 仅取启用状态的。"""
    d = config.ref_images_dir()
    if not d.exists():
        return []
    enabled = config.load_config().get("ref_images_enabled") or {}
    paths = sorted((p for p in d.iterdir()
                    if p.is_file() and p.suffix.lower() in config.WALLPAPER_EXTS
                    and enabled.get(p.name, True)),
                   key=lambda p: p.name)
    return paths[:limit]


def ffmpeg_install_running() -> bool:
    from . import server
    return bool(server._FFMPEG_INSTALL["running"])


def ffmpeg_install_error() -> str | None:
    from . import server
    return server._FFMPEG_INSTALL["error"]


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
