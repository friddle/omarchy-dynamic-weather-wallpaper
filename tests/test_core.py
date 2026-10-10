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
        template = "{weather_cn} {temp} {solarterm_cn} {city} {no_such_placeholder}"
        tags = naming.compose_tags(self.weather(), dt.datetime(2026, 2, 5, 13), self.NAMING)
        out = naming.fill_prompt(template, tags, "杭州市", "westlake")
        self.assertIn("雨", out)
        self.assertIn("立春", out)
        self.assertIn("杭州市", out)
        self.assertIn("{no_such_placeholder}", out)  # 未知占位符原样保留


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
