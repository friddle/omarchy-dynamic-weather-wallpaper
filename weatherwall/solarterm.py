"""二十四节气计算（寿星通式，21 世纪 C 值表，覆盖 2000-2099 年）。

用于把日期映射成文件名里的节气标签，如 寒露 -> colddew。
"""

import datetime as _dt

# (顺序, 中文名, 英文标签, 21世纪C值, 所在月份)
# 顺序按一年内出现先后：小寒(1月) ... 冬至(12月)
TERMS = [
    ("小寒", "minorcold", 5.4055, 1),
    ("大寒", "majorcold", 20.12, 1),
    ("立春", "springbegin", 3.87, 2),
    ("雨水", "rainwater", 18.73, 2),
    ("惊蛰", "insectsawaken", 5.63, 3),
    ("春分", "springequinox", 20.646, 3),
    ("清明", "clearandbright", 4.81, 4),
    ("谷雨", "grainrain", 20.1, 4),
    ("立夏", "summerbegin", 5.52, 5),
    ("小满", "grainbuds", 21.04, 5),
    ("芒种", "graininear", 5.678, 6),
    ("夏至", "summersolstice", 21.37, 6),
    ("小暑", "minorheat", 7.108, 7),
    ("大暑", "majorheat", 22.83, 7),
    ("立秋", "autumnbegin", 7.5, 8),
    ("处暑", "endofheat", 23.13, 8),
    ("白露", "whitedew", 7.646, 9),
    ("秋分", "autumnequinox", 23.042, 9),
    ("寒露", "colddew", 8.318, 10),
    ("霜降", "frostfall", 23.438, 10),
    ("立冬", "winterbegin", 7.438, 11),
    ("小雪", "minorsnow", 22.36, 11),
    ("大雪", "majorsnow", 7.18, 12),
    ("冬至", "wintersolstice", 21.94, 12),
]

# 公式在个别年份有±1天偏差，已知修正(年份 -> 天数偏移)
_EXCEPTIONS = {
    ("大寒", 2082): 1,
    ("雨水", 2026): 1,
    ("春分", 2084): 1,
}

# 英文标签 -> 展示名(多语言)
SOLARTERM_EN = {
    "minorcold": "Minor Cold", "majorcold": "Major Cold",
    "springbegin": "Start of Spring", "rainwater": "Rain Water",
    "insectsawaken": "Insects Awaken", "springequinox": "Spring Equinox",
    "clearandbright": "Pure Brightness", "grainrain": "Grain Rain",
    "summerbegin": "Start of Summer", "grainbuds": "Grain Buds",
    "graininear": "Grain in Ear", "summersolstice": "Summer Solstice",
    "minorheat": "Minor Heat", "majorheat": "Major Heat",
    "autumnbegin": "Start of Autumn", "endofheat": "End of Heat",
    "whitedew": "White Dew", "autumnequinox": "Autumn Equinox",
    "colddew": "Cold Dew", "frostfall": "Frost's Descent",
    "winterbegin": "Start of Winter", "minorsnow": "Minor Snow",
    "majorsnow": "Major Snow", "wintersolstice": "Winter Solstice",
}

SOLARTERM_CN = {en: cn for cn, en, _, _ in TERMS}

# 节气 -> 符号字形(挂件 {solarterm_icon} 占位符; 按季节气候近似:
# 春分/秋分用 ☼, 雨水/谷雨/芒种 ☂, 惊蛰 ⚡, 夏季 ☀, 秋 ⛅☁, 冬/霜 ❄)
SOLARTERM_ICON = {
    "minorcold": "❄", "majorcold": "❄",
    "springbegin": "⛅", "rainwater": "☂", "insectsawaken": "⚡",
    "springequinox": "☼", "clearandbright": "☼", "grainrain": "☂",
    "summerbegin": "☀", "grainbuds": "☀", "graininear": "☂", "summersolstice": "☀",
    "minorheat": "☀", "majorheat": "☀",
    "autumnbegin": "⛅", "endofheat": "⛅", "whitedew": "☁", "autumnequinox": "☼",
    "colddew": "☁", "frostfall": "❄",
    "winterbegin": "❄", "minorsnow": "❄", "majorsnow": "❄", "wintersolstice": "❄",
}


def solarterm_display(en_tag: str, lang: str = "en") -> str:
    return SOLARTERM_EN.get(en_tag, en_tag) if lang == "en" else SOLARTERM_CN.get(en_tag, en_tag)


def term_date(year: int, index: int) -> _dt.date:
    """计算某年第 index 个节气(0=小寒)的具体日期。"""
    _, _, c, month = TERMS[index]
    y = year % 100
    day = int(y * 0.2422 + c) - int(y / 4)
    day += _EXCEPTIONS.get((TERMS[index][0], year), 0)
    return _dt.date(year, month, day)


def current_term(date: _dt.date | None = None) -> tuple[str, str]:
    """返回 (中文名, 英文标签)：当前日期所处节气(最近一个已到节气)。

    一年边界处理：1 月 1 日~小寒 之间属于上一年的冬至。
    """
    if date is None:
        date = _dt.date.today()
    candidates: list[tuple[_dt.date, str, str]] = []
    for year in (date.year - 1, date.year):
        for i, (cn, en, _, _) in enumerate(TERMS):
            candidates.append((term_date(year, i), cn, en))
    candidates.sort()
    current = (None, "冬至", "wintersolstice")
    for d, cn, en in candidates:
        if d <= date:
            current = (d, cn, en)
        else:
            break
    return current[1], current[2]


def next_term(date: _dt.date | None = None) -> tuple[str, str, _dt.date]:
    """下一个节气，用于展示与预估下次切换。"""
    if date is None:
        date = _dt.date.today()
    candidates: list[tuple[_dt.date, str, str]] = []
    for year in (date.year, date.year + 1):
        for i, (cn, en, _, _) in enumerate(TERMS):
            candidates.append((term_date(year, i), cn, en))
    candidates.sort()
    for d, cn, en in candidates:
        if d > date:
            return cn, en, d
    return ("小寒", "minorcold", _dt.date(date.year + 1, 1, 6))
