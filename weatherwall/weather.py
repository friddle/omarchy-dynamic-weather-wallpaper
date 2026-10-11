"""天气获取：国内(itboy, 免key) / 国外(open-meteo, 免key) 双通道，可配置。

统一输出 WeatherInfo:
  tag          统一天气标签: sunny/partlycloudy/cloudy/overcast/fog/haze/
               drizzle/rain/heavyrain/snow/thundershower/wind
  temp_current 当前气温(℃)
  temp_min/max 当日最低/最高(℃)
  city         城市名
  desc         原始天气描述(用于展示)
"""

import re
import urllib.parse

from . import net

# 内置国内城市 -> itboy 城市码(中国气象局城市代码)
CITY_CODES = {
    "北京": "101010100", "beijing": "101010100",
    "上海": "101020100", "shanghai": "101020100",
    "天津": "101030100", "tianjin": "101030100",
    "重庆": "101040100", "chongqing": "101040100",
    "广州": "101280101", "guangzhou": "101280101",
    "深圳": "101280601", "shenzhen": "101280601",
    "杭州": "101210101", "hangzhou": "101210101",
    "宁波": "101210401", "ningbo": "101210401",
    "温州": "101210701", "wenzhou": "101210701",
    "南京": "101190101", "nanjing": "101190101",
    "苏州": "101190401", "suzhou": "101190401",
    "无锡": "101190201", "wuxi": "101190201",
    "成都": "101270101", "chengdu": "101270101",
    "武汉": "101200101", "wuhan": "101200101",
    "长沙": "101250101", "changsha": "101250101",
    "西安": "101110101", "xian": "101110101",
    "郑州": "101180101", "zhengzhou": "101180101",
    "济南": "101120101", "jinan": "101120101",
    "青岛": "101120200", "qingdao": "101120200",
    "沈阳": "101070101", "shenyang": "101070101",
    "大连": "101070201", "dalian": "101070201",
    "哈尔滨": "101050101", "haerbin": "101050101", "harbin": "101050101",
    "长春": "101060101", "changchun": "101060101",
    "石家庄": "101090101", "shijiazhuang": "101090101",
    "太原": "101100101", "taiyuan": "101100101",
    "合肥": "101220101", "hefei": "101220101",
    "福州": "101230101", "fuzhou": "101230101",
    "厦门": "101230201", "xiamen": "101230201",
    "昆明": "101290101", "kunming": "101290101",
    "贵阳": "101260101", "guiyang": "101260101",
    "南宁": "101300101", "nanning": "101300101",
    "海口": "101310101", "haikou": "101310101",
    "兰州": "101160001", "lanzhou": "101160001",
    "西宁": "101150001", "xining": "101150001",
    "银川": "101170101", "yinchuan": "101170101",
    "乌鲁木齐": "101130101", "wulumuqi": "101130101", "urumqi": "101130101",
    "拉萨": "101140101", "lasa": "101140101", "lhasa": "101140101",
    "呼和浩特": "101080101", "huhehaote": "101080101", "hohhot": "101080101",
    "南昌": "101240101", "nanchang": "101240101",
    "香港": "101320101", "hongkong": "101320101",
    "台北": "101340101", "taibei": "101340101", "taipei": "101340101",
}

WEATHER_TAG_CN = {
    "sunny": "晴", "partlycloudy": "晴间多云", "cloudy": "多云", "overcast": "阴",
    "fog": "雾", "haze": "霾", "drizzle": "小雨", "rain": "雨",
    "heavyrain": "大雨", "snow": "雪", "thundershower": "雷阵雨", "wind": "大风",
}

WEATHER_TAG_EN = {
    "sunny": "Sunny", "partlycloudy": "Partly Cloudy", "cloudy": "Cloudy", "overcast": "Overcast",
    "fog": "Fog", "haze": "Haze", "drizzle": "Drizzle", "rain": "Rain",
    "heavyrain": "Heavy Rain", "snow": "Snow", "thundershower": "Thunderstorm", "wind": "Windy",
}

# 天气 -> 符号字形(挂件 {icon} 占位符用; 由 Noto Sans Symbols2 / Segoe UI Symbol
# 等符号字体渲染, 渲染时按字体覆盖自动过滤, 不支持的字形整行省略)
WEATHER_ICON = {
    "sunny": "☀", "partlycloudy": "⛅", "cloudy": "☁", "overcast": "☁",
    "fog": "☁", "haze": "☁", "drizzle": "☂", "rain": "☂",
    "heavyrain": "☔", "snow": "❄", "thundershower": "☈", "wind": "☁",
}


def weather_display(tag: str, lang: str = "en") -> str:
    return WEATHER_TAG_EN.get(tag, tag) if lang == "en" else WEATHER_TAG_CN.get(tag, tag)


def _wmo_to_tag(code: int) -> str:
    """WMO weather code -> 统一标签。"""
    if code == 0:
        return "sunny"
    if code in (1, 2):
        return "partlycloudy" if code == 1 else "cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 66, 67, 80):
        return "rain"
    if code in (65, 81, 82):
        return "heavyrain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thundershower"
    return "cloudy"


def _cn_to_tag(text: str) -> str:
    """中文天气描述 -> 统一标签（注意先后顺序）。"""
    t = text.strip()
    if "雷" in t:
        return "thundershower"
    if "雨夹雪" in t or "冻雨" in t:
        return "snow"
    if "暴雨" in t or "大雨" in t:
        return "heavyrain"
    if "中雨" in t:
        return "rain"
    if "小雨" in t:
        return "drizzle"
    if "阵雨" in t or "雨" in t:
        return "rain"
    if "雪" in t:
        return "snow"
    if "雾" in t:
        return "fog"
    if "霾" in t or "沙尘" in t or "浮尘" in t or "扬沙" in t:
        return "haze"
    if "大风" in t or "台风" in t:
        return "wind"
    if "阴" in t:
        return "overcast"
    if "多云" in t:
        return "cloudy"
    if "晴" in t:
        return "sunny"
    return "cloudy"


class WeatherError(Exception):
    pass


class WeatherInfo(dict):
    """dict 便于序列化，同时提供属性访问。"""


def _fetch_qweather(cfg: dict, proxy: str) -> WeatherInfo:
    """和风天气 v7 (国内, 需免费 key)。api_host 用控制台分配的专属 Host，默认 devapi。"""
    base = cfg["weather"]
    key = str(base.get("api_key") or "").strip()
    if not key:
        raise WeatherError("qweather 需要填写天气 API Key (console.qweather.com 免费获取)")
    host = str(base.get("api_host") or "").strip().rstrip("/") or "devapi.qweather.com"
    scheme = "https" if not host.startswith("http") else ""
    root = f"{scheme}{host}" if scheme else host
    q = {"key": key, "lang": "zh"}
    # 城市名/LocationID -> id
    lookup = net.http_json(
        f"{root}/v2/city/lookup?" + urllib.parse.urlencode(
            {**q, "location": str(base.get("city") or "杭州")}), timeout=10, proxy=proxy)
    if lookup.get("code") != "200" or not lookup.get("location"):
        raise WeatherError(f"qweather 城市查询失败: {lookup.get('code')}")
    loc = lookup["location"][0]
    now = net.http_json(
        f"{root}/v7/weather/now?" + urllib.parse.urlencode({**q, "location": loc["id"]}),
        timeout=10, proxy=proxy)
    if now.get("code") != "200":
        raise WeatherError(f"qweather 实况失败: {now.get('code')}")
    tmin = tmax = None
    try:
        d3 = net.http_json(
            f"{root}/v7/weather/3d?" + urllib.parse.urlencode({**q, "location": loc["id"]}),
            timeout=10, proxy=proxy)
        if d3.get("code") == "200":
            tmin, tmax = float(d3["daily"][0]["tempMin"]), float(d3["daily"][0]["tempMax"])
    except Exception:  # noqa: BLE001 - 3d 失败不致命
        pass
    cur = float(now["now"]["temp"])
    return WeatherInfo(
        provider="qweather",
        tag=_cn_to_tag(now["now"]["text"]),
        desc=now["now"]["text"],
        temp_current=cur,
        temp_min=tmin if tmin is not None else cur,
        temp_max=tmax if tmax is not None else cur,
        city=loc.get("name", str(base.get("city", ""))),
    )


def _owm_to_tag(code: int) -> str:
    """OpenWeatherMap condition id -> 统一标签。"""
    if code == 800:
        return "sunny"
    if code == 801:
        return "partlycloudy"
    if code == 802:
        return "cloudy"
    if code in (803, 804):
        return "overcast"
    if 200 <= code < 300:
        return "thundershower"
    if 300 <= code < 400:
        return "drizzle"
    if code in (502, 503, 504, 522, 531):
        return "heavyrain"
    if 500 <= code < 600:
        return "rain"
    if 600 <= code < 700:
        return "snow"
    if code == 741:
        return "fog"
    if 700 <= code < 800:
        return "haze"
    return "cloudy"


def _fetch_openweathermap(cfg: dict, proxy: str) -> WeatherInfo:
    """OpenWeatherMap (国外, 需免费 key)。"""
    base = cfg["weather"]
    key = str(base.get("api_key") or "").strip()
    if not key:
        raise WeatherError("openweathermap 需要填写天气 API Key (home.openweathermap.org 免费获取)")
    url = ("https://api.openweathermap.org/data/2.5/weather?"
           + urllib.parse.urlencode({
               "q": str(base.get("city") or "Hangzhou"),
               "appid": key, "units": "metric", "lang": "zh_cn"}))
    data = net.http_json(url, timeout=12, proxy=proxy)
    if str(data.get("cod")) not in ("200",):
        raise WeatherError(f"openweathermap 返回异常: {data.get('message', data.get('cod'))}")
    code = int(data["weather"][0]["id"])
    tag = _owm_to_tag(code)
    return WeatherInfo(
        provider="openweathermap",
        tag=tag,
        desc=str(data["weather"][0].get("description") or WEATHER_TAG_CN.get(tag, "")),
        temp_current=float(data["main"]["temp"]),
        temp_min=float(data["main"]["temp_min"]),
        temp_max=float(data["main"]["temp_max"]),
        city=str(data.get("name") or base.get("city") or ""),
    )


def resolve_city_code(cfg_weather: dict) -> str:
    """itboy 城市码：优先配置的 city_code，否则按城市名查表，纯数字直接当码。"""
    code = str(cfg_weather.get("city_code") or "").strip()
    if code:
        return code
    city = str(cfg_weather.get("city") or "").strip().lower()
    if city.isdigit() and len(city) == 9:
        return city
    return CITY_CODES.get(city, "101210101")


def _fetch_itboy(cfg: dict, proxy: str) -> WeatherInfo:
    base = cfg["weather"]
    code = resolve_city_code(base)
    url = f"http://t.weather.itboy.net/api/weather/city/{code}"  # 该源 https 握手不稳，走 http
    data = net.http_json(url, timeout=10, proxy=proxy)
    if data.get("status") != 200:
        raise WeatherError(f"itboy 返回异常: {data.get('message')}")
    d = data["data"]
    today = d["forecast"][0]

    def _temp(s: str) -> float | None:
        m = re.search(r"-?\d+(?:\.\d+)?", s or "")
        return float(m.group()) if m else None

    temp_cur = _temp(str(d.get("wendu", "")))
    tmax = _temp(today.get("high", ""))
    tmin = _temp(today.get("low", ""))
    desc = today.get("type", "")
    cur = temp_cur if temp_cur is not None else (tmin or 0)
    return WeatherInfo(
        provider="itboy",
        tag=_cn_to_tag(desc),
        desc=desc,
        temp_current=cur,
        temp_min=tmin if tmin is not None else cur,
        temp_max=tmax if tmax is not None else cur,
        city=data.get("cityInfo", {}).get("city", str(base.get("city", ""))),
    )


def geocode(city: str, proxy: str = "") -> tuple[float, float]:
    """open-meteo geocoding：城市名 -> 经纬度。"""
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?name="
        + urllib.parse.quote(city) + "&count=1&language=zh"
    )
    data = net.http_json(url, timeout=10, proxy=proxy)
    results = data.get("results") or []
    if not results:
        raise WeatherError(f"geocoding 找不到城市: {city}")
    return float(results[0]["latitude"]), float(results[0]["longitude"])


def _fetch_open_meteo(cfg: dict, proxy: str) -> WeatherInfo:
    base = cfg["weather"]
    lat, lon = base.get("latitude"), base.get("longitude")
    geocoded = False
    if not lat or not lon:
        lat, lon = geocode(str(base.get("city") or "hangzhou"), proxy)
        geocoded = True
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=auto"
    )
    data = net.http_json(url, timeout=12, proxy=proxy)
    cur = data["current"]
    daily = data["daily"]
    code = int(cur.get("weather_code", 3))
    tag = _wmo_to_tag(code)
    info = WeatherInfo(
        provider="open-meteo",
        tag=tag,
        desc=weather_display(tag, "en"),
        temp_current=float(cur["temperature_2m"]),
        temp_min=float(daily["temperature_2m_min"][0]),
        temp_max=float(daily["temperature_2m_max"][0]),
        city=str(base.get("city") or ""),
    )
    if geocoded:
        info["latitude"], info["longitude"] = lat, lon
    return info


PROVIDERS = {
    "itboy": _fetch_itboy,
    "open-meteo": _fetch_open_meteo,
    "qweather": _fetch_qweather,
    "openweathermap": _fetch_openweathermap,
}

# 需要填 key 的天气源(设置页提示用)
KEY_REQUIRED_PROVIDERS = {"qweather", "openweathermap"}

# 美国主要城市(open-meteo geocoding 按城市名解析)
US_CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "Austin", "San Jose", "San Francisco",
    "Seattle", "Denver", "Boston", "Miami", "Atlanta", "Las Vegas", "Portland",
    "Washington",
]


def china_cities() -> list[dict]:
    """从 CITY_CODES 去重生成 [{cn, en, code}] 供设置页选择。"""
    seen: dict[str, dict] = {}
    for key, code in CITY_CODES.items():
        is_cn = any(ord(c) > 127 for c in key)
        if code in seen:
            if is_cn:
                seen[code]["cn"] = key
            else:
                seen[code]["en"] = key.capitalize()
        else:
            seen[code] = {"cn": key if is_cn else "", "en": "" if is_cn else key.capitalize(),
                          "code": code}
    return [v for v in seen.values()]


def find_china_city(city: str) -> dict | None:
    """按中文名/英文名匹配内置中国城市。"""
    c = city.strip().lower()
    for item in china_cities():
        if c in (item["cn"], item["en"].lower()):
            return item
    return None


def provider_chain(cfg: dict, region: str) -> list[str]:
    """决定天气源尝试顺序。"""
    setting = str(cfg["weather"].get("provider") or "auto").lower()
    if setting in PROVIDERS:
        return [setting]
    return ["itboy", "open-meteo"] if region == "china" else ["open-meteo"]


def fetch_weather(cfg: dict, region: str) -> WeatherInfo:
    """按顺序尝试天气源，全部失败抛出最后一个错误。国内模式 itboy 失败自动回落 open-meteo。"""
    proxy = net.cfg_proxy(cfg)
    errors = []
    for name in provider_chain(cfg, region):
        try:
            info = PROVIDERS[name](cfg, proxy)
            info["region"] = region
            return info
        except Exception as e:  # noqa: BLE001 - 逐个源收集错误
            errors.append(f"{name}: {e}")
    raise WeatherError("所有天气源均失败 -> " + " | ".join(errors))
