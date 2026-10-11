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

# 时段(按本地小时): 用于 prompt 的昼夜描述与降级调色
DAYPART_EN = {
    "dawn": "Dawn", "morning": "Morning", "noon": "Noon", "afternoon": "Afternoon",
    "evening": "Evening", "night": "Night", "latenight": "Late Night",
}
DAYPART_CN = {
    "dawn": "清晨", "morning": "上午", "noon": "中午", "afternoon": "下午",
    "evening": "傍晚", "night": "晚上", "latenight": "深夜",
}


def daypart_of(hour: int) -> str:
    if 5 <= hour < 8:
        return "dawn"
    if 8 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 20:
        return "evening"
    if 20 <= hour < 23:
        return "night"
    return "latenight"


def daypart_display(tag: str, lang: str = "en") -> str:
    return DAYPART_EN.get(tag, tag) if lang == "en" else DAYPART_CN.get(tag, tag)


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
    daypart = daypart_of(now.hour)
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
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "daypart": daypart,
        "daypart_en": DAYPART_EN[daypart],
        "daypart_cn": DAYPART_CN[daypart],
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


def fill_prompt(template: str, tags: dict, city: str, base_name: str, lang: str = "en") -> str:
    """把占位符填进生图 prompt 模板。

    多语言占位符:
      {weather_name}/{solarterm_name}  按 ui.language 输出
      {weather_en}/{weather_cn}        固定英文/中文
      {weather} {solarterm}            文件名标签(tag, 恒为英文)
    """
    from .solarterm import solarterm_display
    from .weather import weather_display
    repl = {
        **tags,
        "weather_name": weather_display(tags["weather"], lang),
        "weather_en": weather_display(tags["weather"], "en"),
        "weather_cn": weather_display(tags["weather"], "zh"),
        "solarterm_name": solarterm_display(tags["solarterm"], lang),
        "solarterm_en": solarterm_display(tags["solarterm"], "en"),
        "solarterm_cn": solarterm_display(tags["solarterm"], "zh"),
        "daypart_name": daypart_display(tags.get("daypart", ""), lang),
        "city": city,
        "base_name": base_name,
    }
    out = template
    for k, v in repl.items():
        out = out.replace("{" + k + "}", str(v))
    return out
