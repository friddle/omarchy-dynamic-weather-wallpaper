"""核心逻辑单元测试：节气 / 命名 / 标签映射 / 缓存查找 / 配置合并。

运行: python3 -m unittest discover -s tests -v
"""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weatherwall import config, naming, solarterm  # noqa: E402
from weatherwall.weather import _cn_to_tag, _wmo_to_tag, resolve_city_code  # noqa: E402


class TestSolarTerm(unittest.TestCase):
    def test_known_dates_2026(self):
        # 2026 年节气实际日期(公开历表)
        cases = [
            (dt.date(2026, 2, 4), "立春", "springbegin"),
            (dt.date(2026, 3, 20), "春分", "springequinox"),
            (dt.date(2026, 6, 21), "夏至", "summersolstice"),
            (dt.date(2026, 8, 7), "立秋", "autumnbegin"),
            (dt.date(2026, 10, 8), "寒露", "colddew"),
            (dt.date(2026, 12, 22), "冬至", "wintersolstice"),
        ]
        for date, cn, en in cases:
            self.assertEqual(solarterm.current_term(date), (cn, en), f"{date}")

    def test_term_ranges(self):
        # 节气边界之间归属最近的已到节气
        self.assertEqual(solarterm.current_term(dt.date(2026, 2, 3)), ("大寒", "majorcold"))
        self.assertEqual(solarterm.current_term(dt.date(2026, 10, 10)), ("寒露", "colddew"))
        self.assertEqual(solarterm.current_term(dt.date(2026, 10, 23)), ("霜降", "frostfall"))
        # 1月1日属于上一年的冬至
        self.assertEqual(solarterm.current_term(dt.date(2026, 1, 1)), ("冬至", "wintersolstice"))

    def test_all_terms_valid_dates(self):
        for year in (2025, 2026, 2027, 2049):
            for i in range(24):
                d = solarterm.term_date(year, i)
                self.assertEqual(d.year, year)
                self.assertTrue(1 <= d.day <= 31)


class TestNaming(unittest.TestCase):
    NAMING = {"temp_mode": "band", "temp_band": 5, "time_bucket_hours": 4}

    def weather(self, **kw):
        base = {"tag": "rain", "desc": "中雨", "temp_current": 23.4,
                "temp_min": 12.0, "temp_max": 23.0, "city": "杭州市", "provider": "itboy"}
        base.update(kw)
        return base

    def test_band_label(self):
        self.assertEqual(naming.temp_label(self.weather(temp_current=23.4), self.NAMING), "20-25")
        self.assertEqual(naming.temp_label(self.weather(temp_current=-3), self.NAMING), "-5-0")

    def test_minmax_label(self):
        cfg = {"temp_mode": "minmax", "temp_band": 5, "time_bucket_hours": 4}
        self.assertEqual(naming.temp_label(self.weather(temp_min=12, temp_max=23), cfg), "12-23")

    def test_hours_label(self):
        cfg = dict(self.NAMING)
        self.assertEqual(naming.hours_label(dt.datetime(2026, 10, 10, 12, 30), cfg), "1216")
        # 20~24 桶的结束小时按 24 取模回绕为 00
        self.assertEqual(naming.hours_label(dt.datetime(2026, 10, 10, 23, 59), cfg), "2000")
        self.assertEqual(naming.hours_label(dt.datetime(2026, 10, 10, 2, 0), cfg), "0004")

    def test_full_stem(self):
        now = dt.datetime(2026, 2, 5, 13, 0)  # 立春次日 12~16 桶
        tags = naming.compose_tags(self.weather(), now, self.NAMING)
        stem = naming.compose_stem("westlake", tags)
        self.assertEqual(stem, "westlake_rain_1216_20-25_springbegin")

    def test_find_cached(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertIsNone(naming.find_cached(d, "westlake_rain_1216_20-25_springbegin"))
            (d / "westlake_rain_1216_20-25_springbegin.jpg").write_bytes(b"x")
            hit = naming.find_cached(d, "westlake_rain_1216_20-25_springbegin")
            self.assertIsNotNone(hit)
            self.assertEqual(hit.suffix, ".jpg")

    def test_prompt_fill(self):
        tags = naming.compose_tags(self.weather(), dt.datetime(2026, 2, 5, 13), self.NAMING)
        # 语言相关占位符: name 跟随 lang, en/cn 固定
        out_en = naming.fill_prompt(
            "{weather_name}|{weather_en}|{weather_cn}|{solarterm_name}|{solarterm_en}|{solarterm_cn}|{temp}|{city}",
            tags, "Hangzhou", "westlake", lang="en")
        self.assertEqual(out_en, "Rain|Rain|雨|Start of Spring|Start of Spring|立春|20-25|Hangzhou")
        out_zh = naming.fill_prompt("{weather_name}|{solarterm_name}", tags, "杭州", "westlake", lang="zh")
        self.assertEqual(out_zh, "雨|立春")
        out_default = naming.fill_prompt("{weather_name}", tags, "x", "y")
        self.assertEqual(out_default, "Rain")  # 默认英文
        # 未知占位符原样保留
        self.assertIn("{no_such}", naming.fill_prompt("{no_such}", tags, "c", "b"))


class TestWeatherMaps(unittest.TestCase):
    def test_wmo(self):
        cases = {0: "sunny", 1: "partlycloudy", 2: "cloudy", 3: "overcast", 45: "fog",
                 61: "rain", 65: "heavyrain", 71: "snow", 95: "thundershower", 82: "heavyrain"}
        for code, tag in cases.items():
            self.assertEqual(_wmo_to_tag(code), tag, f"wmo {code}")

    def test_cn(self):
        cases = {"晴": "sunny", "多云": "cloudy", "阴": "overcast", "小雨": "drizzle",
                 "中雨": "rain", "大雨": "heavyrain", "雷阵雨": "thundershower",
                 "雨夹雪": "snow", "小雪": "snow", "雾": "fog", "霾": "haze"}
        for text, tag in cases.items():
            self.assertEqual(_cn_to_tag(text), tag, text)

    def test_city_codes(self):
        self.assertEqual(resolve_city_code({"city": "hangzhou", "city_code": ""}), "101210101")
        self.assertEqual(resolve_city_code({"city": "杭州", "city_code": ""}), "101210101")
        self.assertEqual(resolve_city_code({"city": "x", "city_code": "101010100"}), "101010100")
        self.assertEqual(resolve_city_code({"city": "101010100", "city_code": ""}), "101010100")
        self.assertEqual(resolve_city_code({"city": "unknown-city", "city_code": ""}), "101210101")


class TestConfig(unittest.TestCase):
    def test_base_stem_sanitized(self):
        self.assertEqual(config.base_stem({"base_image": "West Lake.jpg"}), "west_lake")
        self.assertEqual(config.base_stem({"base_image": "西湖.jpg"}), "wallpaper")
        self.assertEqual(config.base_stem({"base_image": ""}), "wallpaper")

    def test_legacy_prompt_migration(self):
        import json
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "config.json"
            f.write_text(json.dumps({"generator": {"prompt": config.LEGACY_PROMPT_ZH}}), encoding="utf-8")
            with mock.patch("weatherwall.config.config_file", return_value=f):
                cfg = config.load_config()
            self.assertEqual(cfg["generator"]["prompt"], config.DEFAULT_PROMPT)
            # 已自定义的 prompt 不被覆盖
            f.write_text(json.dumps({"generator": {"prompt": "my own {temp}"}}), encoding="utf-8")
            with mock.patch("weatherwall.config.config_file", return_value=f):
                cfg = config.load_config()
            self.assertEqual(cfg["generator"]["prompt"], "my own {temp}")


class TestDisplayI18n(unittest.TestCase):
    def test_weather_display(self):
        from weatherwall.weather import weather_display
        self.assertEqual(weather_display("rain", "en"), "Rain")
        self.assertEqual(weather_display("rain", "zh"), "雨")
        self.assertEqual(weather_display("thundershower", "en"), "Thunderstorm")

    def test_solarterm_display(self):
        from weatherwall.solarterm import solarterm_display
        self.assertEqual(solarterm_display("colddew", "en"), "Cold Dew")
        self.assertEqual(solarterm_display("colddew", "zh"), "寒露")
        self.assertEqual(solarterm_display("springbegin", "zh"), "立春")

    def test_city_picker_data(self):
        from weatherwall.weather import china_cities, find_china_city
        cities = china_cities()
        self.assertTrue(all(c["cn"] and c["en"] and c["code"] for c in cities))
        self.assertGreater(len(cities), 30)
        hz = find_china_city("hangzhou")
        self.assertEqual((hz["cn"], hz["code"]), ("杭州", "101210101"))
        self.assertEqual(find_china_city("Hangzhou")["cn"], "杭州")
        self.assertIsNone(find_china_city("Nowhere"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
