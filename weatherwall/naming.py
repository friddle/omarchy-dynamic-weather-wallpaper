"""标签化命名：天气 tag 化、温度范围化、时段分桶，组合成缓存文件名。

文件名格式: {基准图}_{weather}_{hours}_{temperature}_{solarterm}.{ext}
示例:       westlake_rain_1216_20-25_springbegin.jpg
  weather     统一天气标签 rain/sunny/...
  hours       时段桶(默认4小时一桶, 起止小时拼成4位数字, 如 12~16 时 -> 1216)
  temperature band 模式: 当前温度按区间量化(20-25)；minmax 模式: 当日最低-最高(12-23)
  solarterm   节气英文标签 springbegin/colddew/...
"""

import math
from pathlib import Path

from .solarterm import current_term
from .weather import WEATHER_TAG_CN


def temp_label(info: dict, naming_cfg: dict) -> str:
    mode = (naming_cfg.get("temp_mode") or "band").lower()
    if mode == "minmax":
        return f"{round(info['temp_min'])}-{round(info['temp_max'])}"
    band = int(naming_cfg.get("temp_band") or 5)
    band = max(1, min(30, band))
    t = info.get("temp_current")
    t = info.get("temp_min", 0) if t is None else t
    low = int(math.floor(float(t) / band) * band)
    return f"{low}-{low + band}"


def hours_label(now, naming_cfg: dict) -> str:
    bucket = int(naming_cfg.get("time_bucket_hours") or 4)
    bucket = max(1, min(24, bucket))
    start = now.hour // bucket * bucket
    end = (start + bucket) % 24
    return f"{start:02d}{end:02d}"


def compose_tags(info: dict, now, naming_cfg: dict) -> dict:
    term_cn, term_en = current_term(now.date())
    return {
        "weather": info["tag"],
        "weather_cn": WEATHER_TAG_CN.get(info["tag"], info["tag"]),
        "hours": hours_label(now, naming_cfg),
        "temp": temp_label(info, naming_cfg),
        "temp_value": round(float(info.get("temp_current", 0))),
        "temp_min": round(float(info.get("temp_min", 0))),
        "temp_max": round(float(info.get("temp_max", 0))),
        "solarterm": term_en,
        "solarterm_cn": term_cn,
    }


def compose_stem(base_name: str, tags: dict) -> str:
    return "_".join([
        base_name,
        tags["weather"],
        tags["hours"],
        tags["temp"],
        tags["solarterm"],
    ])


def find_cached(cache_dir: Path, stem: str) -> Path | None:
    """懒加载查询：stem 已有任意扩展名的成品图则直接用。"""
    for p in sorted(cache_dir.glob(stem + ".*")):
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return p
    return None


def fill_prompt(template: str, tags: dict, city: str, base_name: str) -> str:
    """把占位符填进生图 prompt 模板。"""
    repl = {
        **tags,
        "city": city,
        "base_name": base_name,
    }
    out = template
    for k, v in repl.items():
        out = out.replace("{" + k + "}", str(v))
    return out
