"""平台相关的目录约定与配置读写。"""

import json
import os
import sys
from pathlib import Path

APP_NAME = "omarchy-dynamic-wallpaper"

# 默认 Prompt(英文)。中文用户可自行在设置页改为中文模板。
DEFAULT_PROMPT = (
    "Based on this reference photo, create a stunning desktop wallpaper: "
    "weather {weather_name}, temperature around {temp}°C ({temp_min}~{temp_max}°C), "
    "solar term {solarterm_name}, daytime segment {hours}. "
    "Preserve the original composition, main subject and color palette, "
    "naturally blending in the weather and seasonal atmosphere. "
    "Photorealistic, rich details, no text or watermark."
)

# 旧版中文默认 Prompt(升级时自动替换为新的英文默认)
LEGACY_PROMPT_ZH = (
    "以这张基准照片为基础创作一张精美的桌面壁纸：当前天气为{weather_cn}，"
    "气温约{temp}℃（{temp_min}~{temp_max}℃），节气为{solarterm_cn}，时段为{hours}。"
    "保持原图的构图、主体与色调风格，自然地融入上述天气、温度与季节氛围，"
    "画面真实自然、细节丰富，不要出现任何文字和水印。"
)

DEFAULT_CONFIG = {
    # auto: 初始化时探测(google 通->global, 不通->china)，可手动覆盖
    "region": "auto",
    "weather": {
        # auto: 按 region 选 (china->itboy, global->open-meteo)；
        # 也可显式 itboy / open-meteo (免key) 或 qweather / openweathermap (需 api_key)
        "provider": "auto",
        "city": "hangzhou",
        "city_code": "",        # itboy 9 位城市码，留空则按城市名查内置表
        "latitude": None,       # open-meteo 可直接指定坐标，留空则按城市名 geocode
        "longitude": None,
        "api_key": "",          # 仅 qweather / openweathermap 需要
        "api_host": "",         # 仅 qweather: 控制台分配的专属 API Host(如 abc123.re.qweatherapi.com)
    },
    "refresh_minutes": 30,
    "network": {
        # 出口代理，如 http://10.10.32.8:7890；留空则直连(仍会读取系统 http_proxy 环境变量)
        "proxy": "",
    },
    "naming": {
        "temp_mode": "band",     # band: 温度按区间量化(如 20-25) | minmax: 当日最低-最高(如 12-23)
        "temp_band": 5,
        "time_bucket_hours": 4,  # 时段桶大小(小时)，生成 hours 标签如 1216
    },
    "generator": {
        "base_url": "https://api.openai.com/v1",  # 任意 OpenAI 兼容生图服务
        "api_key": "",
        "model": "gpt-image-1",
        "size": "auto",           # auto / 1024x1024 / 1536x1024 / 1024x1536
        "prompt": DEFAULT_PROMPT,
        "timeout_seconds": 300,
    },
    "server": {"host": "127.0.0.1", "port": 8765},
    "wallpaper": {"apply": True},
    "base_image": "",             # base_images/ 下的文件名
    "ui": {
        "language": "en",         # 展示语言: en(默认) / zh
    },
}


def _base_dir() -> Path:
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        p = Path(root) / APP_NAME
    else:
        p = Path.home() / ".config" / APP_NAME
    return p


def _cache_dir() -> Path:
    if os.name == "nt":
        return config_dir() / "cache"
    return Path.home() / ".cache" / APP_NAME


def config_dir() -> Path:
    return _base_dir()


def config_file() -> Path:
    return _base_dir() / "config.json"


def base_images_dir() -> Path:
    return _base_dir() / "base_images"


def cache_dir() -> Path:
    return _cache_dir() / "wallpapers"


def state_file() -> Path:
    return _cache_dir() / "state.json"


def ensure_dirs() -> None:
    for d in (config_dir(), base_images_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = config_file()
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"配置文件损坏 {path}: {e}") from e

        def merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    merge(dst[k], v)
                else:
                    dst[k] = v

        merge(cfg, user)
        # 升级迁移: 旧中文默认 Prompt 自动换成新的英文默认
        if cfg["generator"].get("prompt") == LEGACY_PROMPT_ZH:
            cfg["generator"]["prompt"] = DEFAULT_PROMPT
    return cfg


def save_config(cfg: dict) -> None:
    ensure_dirs()
    path = config_file()
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def active_base_path(cfg: dict) -> Path | None:
    """当前生效的基准图路径；未配置或文件不存在返回 None。"""
    name = (cfg.get("base_image") or "").strip()
    if not name:
        return None
    p = base_images_dir() / name
    return p if p.exists() else None


def base_stem(cfg: dict) -> str:
    """用于目标文件名的基准图名(取上传文件名主干，规范化为小写字母数字)。"""
    name = (cfg.get("base_image") or "").strip()
    stem = Path(name).stem if name else "wallpaper"
    out = []
    for ch in stem.lower():
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch)
        elif ch.strip() == "":
            out.append("_")
    stem = "".join(out).strip("_") or "wallpaper"
    return stem
