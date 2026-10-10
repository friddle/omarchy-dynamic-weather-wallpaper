"""网络区域探测：初始化时判断走国内还是国外通道。

google 通 -> 国外通道；不通但国内站点通 -> 国内通道。
配置了代理(network.proxy)时探测走代理，通常结果即为 global。
"""

import time

from . import net

GLOBAL_PROBE = "https://www.google.com/generate_204"
CHINA_PROBE = "https://www.baidu.com"

_REGION_CACHE = {"region": None, "ts": 0.0}
_CACHE_TTL = 3600  # 探测结果缓存 1 小时，避免每轮循环都去撞墙


def probe_region(cfg: dict | None = None, force: bool = False) -> str | None:
    """返回 "global" / "china"；完全断网返回 None。"""
    now = time.time()
    if not force and _REGION_CACHE["region"] and now - _REGION_CACHE["ts"] < _CACHE_TTL:
        return _REGION_CACHE["region"]

    proxy = net.cfg_proxy(cfg)
    if net.reachable(GLOBAL_PROBE, timeout=5, proxy=proxy):
        region = "global"
    elif net.reachable(CHINA_PROBE, timeout=5, proxy=proxy):
        region = "china"
    else:
        return _REGION_CACHE["region"]  # 网络不可用，沿用上次结果

    _REGION_CACHE["region"] = region
    _REGION_CACHE["ts"] = now
    return region


def resolve_region(cfg: dict, force: bool = False) -> str:
    """合并配置：配置了 china/global 直接用，auto 才探测。"""
    setting = (cfg.get("region") or "auto").lower()
    if setting in ("china", "global"):
        return setting
    return probe_region(cfg, force=force) or "china"


def load_cached_region(state: dict) -> str | None:
    """从持久化 state 恢复进程内缓存(重启后避免重复探测)。"""
    if state.get("region") and time.time() - state.get("region_ts", 0) < _CACHE_TTL * 24:
        _REGION_CACHE["region"] = state["region"]
        _REGION_CACHE["ts"] = state["region_ts"]
    return _REGION_CACHE["region"]


def region_cache() -> dict:
    return dict(_REGION_CACHE)
