"""核心逻辑单元测试：节气 / 命名 / 标签映射 / 缓存查找 / 配置合并。

运行: python3 -m unittest discover -s tests -v
"""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_seed_base_image(self):
        from weatherwall import config as cfg_mod
        seed = cfg_mod.seed_base_image()
        self.assertIsNotNone(seed)  # 仓库内置 weatherwall/seed/island.png
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(cfg_mod, "config_dir", return_value=root / "cfg"), \
                 mock.patch.object(cfg_mod, "base_images_dir", return_value=root / "cfg" / "base_images"), \
                 mock.patch.object(cfg_mod, "config_file", return_value=root / "cfg" / "config.json"):
                self.assertTrue(cfg_mod.seed_if_empty())       # 首次: 生效
                cfg = cfg_mod.load_config()
                self.assertEqual(cfg["base_image"], "island.png")
                self.assertTrue((root / "cfg" / "base_images" / "island.png").exists())
                self.assertFalse(cfg_mod.seed_if_empty())      # 二次: 不重复
                # 已有基准图时也不覆盖
                cfg["base_image"] = ""
                cfg_mod.save_config(cfg)
                (root / "cfg" / "base_images" / "mine.jpg").write_bytes(b"x")
                self.assertFalse(cfg_mod.seed_if_empty())

    def test_base_image_self_heal(self):
        """基准图自愈: 未配置/丢失时自动回退目录里最新一张。"""
        from weatherwall import config as cfg_mod
        from weatherwall.app import App
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bdir = root / "base_images"
            bdir.mkdir()
            (bdir / "a.png").write_bytes(b"1")
            import time as _t
            _t.sleep(0.02)
            (bdir / "b.jpg").write_bytes(b"2")  # 更新的一张
            app = App.__new__(App)  # 不跑完整 __init__
            app.state = {"log": []}
            app.log = lambda msg: None
            cfg = cfg_mod.DEFAULT_CONFIG
            with mock.patch.object(cfg_mod, "base_images_dir", return_value=bdir), \
                 mock.patch.object(cfg_mod, "save_config", lambda c: None):
                cfg["base_image"] = ""
                cfg2, base_path = app._heal_base_image(cfg)
                self.assertEqual(cfg2["base_image"], "b.jpg")
                self.assertIsNotNone(base_path)
                # 已配置且存在: 不动
                cfg["base_image"] = "a.png"
                cfg2, base_path = app._heal_base_image(cfg)
                self.assertEqual(cfg2["base_image"], "a.png")
                self.assertIsNotNone(base_path)
                # 配置指向不存在的文件: 回退到最新
                cfg["base_image"] = "gone.png"
                cfg2, base_path = app._heal_base_image(cfg)
                self.assertEqual(cfg2["base_image"], "b.jpg")
                # 空目录: 不动
                for f in bdir.iterdir():
                    f.unlink()
                cfg["base_image"] = ""
                cfg2, base_path = app._heal_base_image(cfg)
                self.assertEqual(cfg2["base_image"], "")
                self.assertIsNone(base_path)

    def test_wallpaper_cache_migration(self):
        from weatherwall import config as cfg_mod
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cfg_mod, "cache_dir", return_value=Path(td)):
                # 旧扁平结构
                for name in ("westlake_sunny_1216_25-30_colddew.jpg",
                             "mountainmist_rain_0804_15-20_colddew.jpg",
                             "wallpaper_sunny_1216_25-30_colddew.png"):
                    (Path(td) / name).write_bytes(b"x")
                moved = cfg_mod.migrate_wallpaper_cache()
                self.assertEqual(moved, 3)
                self.assertTrue((Path(td) / "westlake" / "westlake_sunny_1216_25-30_colddew.jpg").exists())
                self.assertTrue((Path(td) / "mountainmist" / "mountainmist_rain_0804_15-20_colddew.jpg").exists())
                self.assertTrue((Path(td) / "wallpaper" / "wallpaper_sunny_1216_25-30_colddew.png").exists())
                self.assertEqual([p.name for p in Path(td).iterdir() if p.is_file()], [])
                # 幂等
                self.assertEqual(cfg_mod.migrate_wallpaper_cache(), 0)
                self.assertEqual(cfg_mod.wallpaper_dir("westlake").name, "westlake")

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
        self.assertEqual(config.base_stem({"base_image": "西湖.jpg"}), "xihu")  # 中文转拼音
        self.assertEqual(config.base_stem({"base_image": ""}), "wallpaper")

    def test_normalize_stem(self):
        cases = {
            "_哲风壁纸_城市天际线-摩天大楼.jpg": "zhefengbizhi_chengshitianjixian_motiandalou",
            "西湖.jpg": "xihu",
            "杭州 West Lake.png": "hangzhou_west_lake",
            "!!!": "base",
            "westlake": "westlake",
            "上海-外滩.jpeg": "shanghai_waitan",
        }
        for name, want in cases.items():
            self.assertEqual(config.normalize_stem(name), want, name)

    def test_legacy_prompt_migration(self):
        import json
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "config.json"
            # 所有旧版默认 prompt 都迁移到最新默认
            for legacy in config.LEGACY_PROMPTS:
                f.write_text(json.dumps({"generator": {"prompt": legacy}}), encoding="utf-8")
                with mock.patch("weatherwall.config.config_file", return_value=f):
                    cfg = config.load_config()
                self.assertEqual(cfg["generator"]["prompt"], config.DEFAULT_PROMPT)
            # 新默认带昼夜与本地时间占位符
            self.assertIn("{daypart_name}", config.DEFAULT_PROMPT)
            self.assertIn("{time}", config.DEFAULT_PROMPT)
            # 上一版默认(含 sun, moon or stars)已列入自动迁移
            self.assertTrue(any("sun, moon or stars" in p for p in config.LEGACY_PROMPTS))
            # 已自定义的 prompt 不被覆盖
            f.write_text(json.dumps({"generator": {"prompt": "my own {temp}"}}), encoding="utf-8")
            with mock.patch("weatherwall.config.config_file", return_value=f):
                cfg = config.load_config()
            self.assertEqual(cfg["generator"]["prompt"], "my own {temp}")
            # 内置基准图默认描述
            self.assertIn("wooden house", config.DEFAULT_BASE_PROMPT)


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


class TestDegradedGeneration(unittest.TestCase):
    """生图失败时降级直用基准图，轮次不中断，且不污染缓存。"""

    def test_generation_failure_falls_back_to_base(self):
        import json
        import threading
        from weatherwall import app as app_mod
        from weatherwall.app import App
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bdir = root / "base_images"
            bdir.mkdir()
            (bdir / "base.png").write_bytes(b"PNGDATA")
            cdir = root / "cache"
            cdir.mkdir()
            cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
            cfg["base_image"] = "base.png"
            cfg["weather"]["city"] = "hangzhou"
            app = App.__new__(App)  # 不跑完整 __init__
            app._lock = threading.Lock()
            app.state = {"log": []}
            app.log = lambda msg: None
            info = {"tag": "sunny", "desc": "Sunny", "temp_current": 20.0,
                    "temp_min": 10.0, "temp_max": 25.0, "city": "Hangzhou",
                    "provider": "test"}
            with mock.patch.object(config, "base_images_dir", return_value=bdir), \
                 mock.patch.object(config, "cache_dir", return_value=cdir), \
                 mock.patch.object(config, "state_file", return_value=root / "state.json"), \
                 mock.patch.object(config, "config_file", return_value=root / "config.json"), \
                 mock.patch.object(config, "config_dir", return_value=root), \
                 mock.patch.object(app_mod.region, "resolve_region", return_value="china"), \
                 mock.patch.object(app_mod, "fetch_weather", return_value=info), \
                 mock.patch.object(app_mod.generate, "generate_image",
                                   side_effect=RuntimeError("boom")), \
                 mock.patch.object(app_mod.wallpaper, "set_wallpaper") as sw:
                res = app.run_once(apply=True)
                self.assertTrue(res["ok"])
                self.assertTrue(res["degraded"])
                self.assertEqual(res["file"], str(bdir / "base.png"))
                sw.assert_called_once()
                self.assertEqual(app.state["last_gen_error"], "boom")
                self.assertIsNone(app.state["last_error"])
                self.assertTrue(app.state["last_applied"])
                # 降级结果不写入缓存，接口恢复后可正常生成
                self.assertEqual([p for p in cdir.rglob("*") if p.is_file()], [])

    def test_generation_failure_without_base_raises(self):
        import json
        import threading
        from weatherwall import app as app_mod
        from weatherwall.app import App
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bdir = root / "base_images"
            bdir.mkdir()
            cdir = root / "cache"
            cdir.mkdir()
            cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))  # 无基准图
            app = App.__new__(App)
            app._lock = threading.Lock()
            app.state = {"log": []}
            app.log = lambda msg: None
            info = {"tag": "sunny", "desc": "Sunny", "temp_current": 20.0,
                    "temp_min": 10.0, "temp_max": 25.0, "city": "x",
                    "provider": "test"}
            with mock.patch.object(config, "base_images_dir", return_value=bdir), \
                 mock.patch.object(config, "cache_dir", return_value=cdir), \
                 mock.patch.object(config, "state_file", return_value=root / "state.json"), \
                 mock.patch.object(config, "config_file", return_value=root / "config.json"), \
                 mock.patch.object(config, "config_dir", return_value=root), \
                 mock.patch.object(app_mod.region, "resolve_region", return_value="china"), \
                 mock.patch.object(app_mod, "fetch_weather", return_value=info), \
                 mock.patch.object(app_mod.generate, "generate_image",
                                   side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    app.run_once(apply=True)


class TestWidget(unittest.TestCase):
    def test_fill_lines(self):
        import datetime as dt
        from weatherwall import widget
        info = {"city": "Hangzhou", "temp_current": 23.4, "temp_min": 12.0, "temp_max": 23.0}
        tags = {"weather": "rain", "hours": "1216", "temp": "20-25", "temp_value": 23,
                "temp_min": 12, "temp_max": 23, "solarterm": "springbegin"}
        now = dt.datetime(2026, 2, 5, 13, 5)
        lines = widget.fill_lines(
            ["{city}", "{weather_name} {temp}°C", "自己加的话语 {time}", ""],
            info, tags, now, "en")
        self.assertEqual(lines, ["Hangzhou", "Rain 23°C", "自己加的话语 13:05"])
        # 未知占位符原样保留
        self.assertEqual(widget.fill_lines(["{nope}"], info, tags, now, "en"), ["{nope}"])
        # 全空行 -> 空列表
        self.assertEqual(widget.fill_lines(["", "  "], info, tags, now, "en"), [])

    def test_layout_clamps_and_banner(self):
        from weatherwall import widget
        lay = widget.layout(["a", "b"], 800, 500,
                            {"style": "glass", "scale": 1.0, "position": {"x": 0.9, "y": 0.9}})
        bx, by, bw, bh = lay["box"]
        self.assertLessEqual(bx + bw, 800)
        self.assertLessEqual(by + bh, 500)
        ban = widget.layout(["a"], 800, 500, {"style": "banner"})
        self.assertEqual(ban["box"][1] + ban["box"][3], 500)  # banner 紧贴底部

    def test_ffargs_styles(self):
        from weatherwall import widget
        import datetime as dt
        now = dt.datetime(2026, 10, 11, 12, 0)
        info = {"city": "x", "temp_current": 1, "temp_min": 0, "temp_max": 2}
        tags = {"weather": "sunny", "hours": "1200", "temp": "0-5", "temp_value": 1,
                "temp_min": 0, "temp_max": 2, "solarterm": "colddew"}
        lines = widget.fill_lines(["{city}"], info, tags, now, "en")
        for style in ("glass", "card", "minimal", "banner"):
            wcfg = {"style": style, "bg_opacity": 0.55, "scale": 1.0,
                    "position": {"x": 0.05, "y": 0.66}}
            lay = widget.layout(lines, 800, 500, wcfg)
            with tempfile.TemporaryDirectory() as td:
                args = widget._ffargs(lay, wcfg, "/f.ttf", Path(td), 800)
            self.assertIn("drawtext", " ".join(args), style)
            if style == "glass":
                self.assertIn("boxblur", " ".join(args))
            if style == "minimal":
                self.assertNotIn("drawbox", " ".join(args))

    def test_weather_icon_map_and_fill(self):
        import datetime as dt
        from weatherwall import widget
        from weatherwall.weather import WEATHER_ICON, WEATHER_TAG_CN
        from weatherwall.solarterm import SOLARTERM_ICON, TERMS
        # 每种天气都有图标映射; 24 节气都有图标
        self.assertEqual(set(WEATHER_ICON), set(WEATHER_TAG_CN))
        self.assertEqual(set(SOLARTERM_ICON), {en for _, en, _, _ in TERMS})
        info = {"city": "x", "temp_current": 1, "temp_min": 0, "temp_max": 2}
        tags = {"weather": "sunny", "hours": "1200", "temp": "0-5", "temp_value": 1,
                "temp_min": 0, "temp_max": 2, "solarterm": "colddew"}
        lines = widget.fill_lines(["{weather_icon}", "{solarterm_icon}", "{weather_name}"],
                                  info, tags, dt.datetime(2026, 10, 11, 12, 0), "en")
        self.assertEqual(lines, ["☀", "☁", "Sunny"])
        # 旧名 {icon} 仍兼容
        lines = widget.fill_lines(["{icon}"], info, tags,
                                  dt.datetime(2026, 10, 11, 12, 0), "en")
        self.assertEqual(lines, ["☀"])

    def test_icon_font_covers(self):
        from weatherwall import widget
        font = widget.find_icon_font("☀☁☂❄⛈☈☔⛅")
        if font is None:
            self.skipTest("系统无覆盖天气符号的图标字体")
        self.assertTrue(widget.font_covers(font, "☀⛅"))


class TestDaypart(unittest.TestCase):
    def test_daypart_of(self):
        cases = {6: "dawn", 9: "morning", 12: "noon", 15: "afternoon",
                 18: "evening", 21: "night", 23: "latenight", 2: "latenight"}
        for hour, tag in cases.items():
            self.assertEqual(naming.daypart_of(hour), tag, f"hour {hour}")

    def test_compose_tags_time_and_daypart(self):
        info = {"tag": "rain", "temp_current": 10.0, "temp_min": 5.0, "temp_max": 12.0}
        tags = naming.compose_tags(info, dt.datetime(2026, 10, 11, 18, 15), {})
        self.assertEqual(tags["time"], "18:15")
        self.assertEqual(tags["daypart"], "evening")
        self.assertEqual(tags["daypart_cn"], "傍晚")
        out = naming.fill_prompt("{daypart_name}|{time}", tags, "杭州市", "b", lang="zh")
        self.assertEqual(out, "傍晚|18:15")


class TestSchedulerHelpers(unittest.TestCase):
    def test_is_network_error(self):
        from weatherwall.app import is_network_error
        self.assertTrue(is_network_error(
            "所有天气源均失败 -> itboy: <urlopen error [Errno -3] Temporary failure in name resolution>"))
        self.assertTrue(is_network_error("Name or service not known"))
        self.assertTrue(is_network_error("[Errno 101] Network is unreachable"))
        # 连接超时/被拒不算网络未就绪(可能是对端问题)
        self.assertFalse(is_network_error("生图接口连接失败: [Errno 110] Connection timed out"))
        self.assertFalse(is_network_error("生图接口 HTTP 401"))
        self.assertFalse(is_network_error(""))


class TestResolutionFit(unittest.TestCase):
    def test_resolve_size(self):
        from weatherwall.app import resolve_size
        self.assertEqual(resolve_size("auto", (3840, 2160)), "3840x2160")
        self.assertEqual(resolve_size("", (1920, 1080)), "1920x1080")
        self.assertEqual(resolve_size("auto", None), "auto")     # 检测失败回落接口默认
        self.assertEqual(resolve_size("1536x1024", (3840, 2160)), "1536x1024")

    def test_fit_to_cover_crop(self):
        import unittest.mock as m
        from weatherwall import widget, generate
        if not widget.available():
            self.skipTest("ffmpeg 不可用")
        raw = generate.make_placeholder_png((1600, 1000))
        data, ext = widget.fit_to(raw, 800, 600)
        self.assertEqual(ext, "jpg")
        self.assertEqual(widget._probe_size(data), (800, 600))
        # 已是目标尺寸: 原样返回不重压缩
        same, ext2 = widget.fit_to(data, 800, 600)
        self.assertEqual(ext2, "jpg")
        self.assertEqual(widget._probe_size(same), (800, 600))


    def test_nearest_sizes(self):
        from weatherwall import app
        # 2560x1600(16:10): 宽高比最近的是 3:2 的 1536x1024, 其后按面积排 16:9 档
        self.assertEqual(app.nearest_sizes("2560x1600")[0], "1536x1024")
        order = app.nearest_sizes("2560x1600")
        self.assertEqual(order, ["1536x1024", "2560x1440", "1920x1080",
                                 "3840x2160", "1024x1024", "1024x1536"])
        # 16:9 屏幕: 同比例下面积最近的优先
        self.assertEqual(app.nearest_sizes("2560x1440")[0], "1920x1080")
        # 竖屏: 候选转竖版
        self.assertEqual(app.nearest_sizes("1080x1920")[0], "1024x1536")
        # 已知被拒的尺寸被剔除; 目标本身不在候选里
        app._UNSUPPORTED.add("1536x1024")
        try:
            self.assertNotIn("1536x1024", app.nearest_sizes("2560x1600"))
        finally:
            app._UNSUPPORTED.discard("1536x1024")
        # 目标无法解析 -> 通用横版
        self.assertEqual(app.nearest_sizes("auto"), ["1536x1024"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
