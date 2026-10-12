"""标签化命名：天气 tag 化、温度范围化、时段词化，组合成缓存文件名。

文件名格式: {基准图}_{weather}_{period}[_{temperature}]_{solarterm}.{ext}
示例:       westlake_rain_afternoon_20-25_springbegin.jpg
  weather     统一天气标签 rain/sunny/...
  period      时段词标签 morning/forenoon/noon/afternoon/dusk/evening/latenight
  temperature band 模式: 当前温度按区间量化(20-25)；minmax 模式: 当日最低-最高(12-23)
              默认不参与缓存键(可在设置页勾选加入)
  solarterm   节气英文标签 springbegin/colddew/...

缓存键构成可配置(naming.cache_key): 天气/时段/节气默认参与, 温度/日期默认不参与;
日期不参与 AI 图缓存键, 但日历挂件按日期重新合成(两段式管线)。
"""

import math
import re
from pathlib import Path

from .solarterm import current_term
from .weather import WEATHER_TAG_CN

# 时段(按本地小时): 用于 prompt 的昼夜描述、挂件时段词与缓存键
DAYPART_EN = {
    "morning": "Early Morning", "forenoon": "Morning", "noon": "Noon",
    "afternoon": "Afternoon", "dusk": "Dusk", "evening": "Evening",
    "latenight": "Late Night",
}
DAYPART_CN = {
    "morning": "早晨", "forenoon": "上午", "noon": "中午", "afternoon": "下午",
    "dusk": "傍晚", "evening": "晚上", "latenight": "深夜",
}
PERIOD_KEYS = ("morning", "forenoon", "noon", "afternoon", "dusk", "evening", "latenight")


def daypart_of(hour: int) -> str:
    if 5 <= hour < 8:
        return "morning"
    if 8 <= hour < 11:
        return "forenoon"
    if 11 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 20:
        return "dusk"
    if 20 <= hour < 23:
        return "evening"
    return "latenight"


def daypart_display(tag: str, lang: str = "en") -> str:
    table = DAYPART_EN if lang == "en" else DAYPART_CN
    return table.get(tag, tag)


def period_word_repl(tags: dict, lang: str = "en") -> dict:
    """各时段词占位符: 仅当前渲染时段的 key 输出本地词, 其余为空(空行自动丢弃)。"""
    cur = str(tags.get("daypart") or tags.get("period") or "")
    return {k: (daypart_display(k, lang) if k == cur else "") for k in PERIOD_KEYS}


# ---------- 带格式的时间/日期占位符: {time_HH:mm} {date_YYYY-MM-DD} 等 ----------

_DT_TOKENS = ("YYYY", "YY", "MM", "DD", "HH", "mm", "M", "D", "H", "m")
_DT_FMT = {"YYYY": "%Y", "YY": "%y", "MM": "%m", "DD": "%d", "HH": "%H",
           "mm": "%M", "M": lambda v: str(int(v)), "D": lambda v: str(int(v)),
           "H": lambda v: str(int(v)), "m": lambda v: str(int(v))}
_DT_PLACEHOLDER = re.compile(r"\{(?:time|date)_([^{}]*)\}")


def format_clock(now, spec: str) -> str:
    """把 HH/MM/DD 之类的 token 串解析成格式化结果, 未识别字符原样保留。"""
    out = []
    i = 0
    while i < len(spec):
        for tok in _DT_TOKENS:
            if spec.startswith(tok, i):
                v = now.strftime(_DT_FMT[tok]) if isinstance(_DT_FMT[tok], str) \
                    else _DT_FMT[tok](now.strftime({"M": "%m", "D": "%d", "H": "%H", "m": "%M"}[tok]))
                out.append(v)
                i += len(tok)
                break
        else:
            out.append(spec[i])
            i += 1
    return "".join(out)


def expand_dt_placeholders(text: str, now) -> str:
    """展开模板里的 {time_..}/{date_..} 带格式占位符。"""
    return _DT_PLACEHOLDER.sub(lambda m: format_clock(now, m.group(1)), text)


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
        "date_key": now.strftime("%Y%m%d"),
        "daypart": daypart,
        "daypart_en": DAYPART_EN[daypart],
        "daypart_cn": DAYPART_CN[daypart],
        "period": daypart,
        "period_en": DAYPART_EN[daypart],
        "period_cn": DAYPART_CN[daypart],
    }


def compose_stem(base_name: str, tags: dict, key_cfg: dict | None = None) -> str:
    """按 cache_key 配置组合缓存键; 未给配置用默认(天气/时段/节气参与, 温度/日期不参与)。"""
    key = key_cfg or {}
    parts = [base_name]
    if key.get("weather", True):
        parts.append(tags["weather"])
    if key.get("period", True):
        parts.append(tags["daypart"])
    if key.get("temp", False):
        parts.append(tags["temp"])
    if key.get("date", False):
        parts.append(tags["date_key"])
    if key.get("solarterm", True):
        parts.append(tags["solarterm"])
    return "_".join(parts)


def find_cached(cache_dir: Path, stem: str) -> Path | None:
    """懒加载查询：stem 已有任意扩展名的成品图则直接用。"""
    for p in sorted(cache_dir.glob(stem + ".*")):
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return p
    return None


def fill_prompt(template: str, tags: dict, city: str, base_name: str, lang: str = "en",
                ref_names: list[str] | None = None) -> str:
    """把占位符填进生图 prompt 模板。

    多语言占位符:
      {weather_name}/{solarterm_name}/{period_name}  按 ui.language 输出
      {weather_en}/{weather_cn} 等                   固定语言
      {weather} {solarterm} {period}                 文件名标签(tag, 恒为英文)
      {morning}/{forenoon}/...                       仅当前时段输出该词, 其余为空
      {time_HH:mm} {date_YYYY-MM-DD}                 带格式时间/日期
      {ref_names}                                    参考图名(逗号连接, 无参考图为空)
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
        "period_name": daypart_display(tags.get("daypart", ""), lang),
        "daypart_name": daypart_display(tags.get("daypart", ""), lang),
        "city": city,
        "base_name": base_name,
        "ref_names": ", ".join(str(n) for n in (ref_names or [])),
        **period_word_repl(tags, lang),
    }
    out = template
    for k, v in repl.items():
        out = out.replace("{" + k + "}", str(v))
    return expand_dt_placeholders(out, _prompt_now(tags))


def _prompt_now(tags: dict):
    """prompt 里时间占位符的基准时刻: 优先用标签里的 date/time(生成那一刻)。"""
    import datetime as _dt
    try:
        d = _dt.datetime.strptime(str(tags.get("date", "")), "%Y-%m-%d")
        h, m = map(int, str(tags.get("time", "0:0")).split(":")[:2])
        return d.replace(hour=h, minute=m)
    except ValueError:
        return _dt.datetime.now()
