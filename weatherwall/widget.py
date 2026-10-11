"""信息挂件：把天气/温度等字段排版后合成到壁纸上(可选功能)。

- 字段模板行支持占位符({city} {temp} {weather_name} {solarterm_name} {time} 等),
  可在设置页自由编辑/增删/排序, 也可写自定义话语
- 样式: glass(毛玻璃) / card(卡片) / minimal(极简阴影字) / banner(底部横幅)
- 位置: 挂件盒中心点相对图片坐标(0~1), 默认右上角, 设置页可拖拽; banner 固定底部
- 渲染后端: ffmpeg(drawtext/drawbox/boxblur), 无需 Pillow; 缺 ffmpeg 则跳过合成
- 背景不透明度 bg_opacity 可配置

compose() 返回 JPEG bytes; 失败抛 WidgetError, 调用方应回退使用原图。
"""

import datetime
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from .weather import weather_display
from .solarterm import solarterm_display


class WidgetError(Exception):
    pass


def available() -> bool:
    """挂件功能可用: 需要 ffmpeg 与至少一个字体文件。"""
    return bool(shutil.which("ffmpeg") and find_font())


def fit_to(data: bytes, width: int, height: int) -> tuple[bytes, str]:
    """缩放并居中裁剪(cover)到目标分辨率, 让壁纸精确匹配显示器;
    已是目标尺寸则原样返回(不重压缩)。"""
    from .generate import _ext_of
    try:
        if _probe_size(data) == (width, height):
            return data, _ext_of(data)
    except WidgetError:
        pass
    if not shutil.which("ffmpeg"):
        raise WidgetError("未找到 ffmpeg, 无法适配分辨率")
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={width}:{height}")
    with tempfile.TemporaryDirectory(prefix="weatherwall-fit-") as td:
        out = Path(td) / "out.jpg"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", "-", "-vf", vf, "-frames:v", "1", "-q:v", "2", str(out)]
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise WidgetError("ffmpeg 分辨率适配超时") from e
        if r.returncode != 0 or not out.exists():
            raise WidgetError(f"ffmpeg 分辨率适配失败: {r.stderr.decode('utf-8', 'replace')[:200]}")
        return out.read_bytes(), "jpg"


# ---------- 字段模板填充 ----------

def build_repl(info: dict, tags: dict, now: datetime.datetime, lang: str = "en") -> dict:
    """挂件模板可用占位符。{temp} 是当前温度(与 prompt 模板一致), 另加时间日期。"""
    return {
        **tags,
        "weather_name": weather_display(tags["weather"], lang),
        "weather_en": weather_display(tags["weather"], "en"),
        "weather_cn": weather_display(tags["weather"], "zh"),
        "solarterm_name": solarterm_display(tags["solarterm"], lang),
        "solarterm_en": solarterm_display(tags["solarterm"], "en"),
        "solarterm_cn": solarterm_display(tags["solarterm"], "zh"),
        "city": str(info.get("city") or ""),
        "temp": _fmt_temp(info.get("temp_current")),
        "temp_min": _fmt_temp(info.get("temp_min")),
        "temp_max": _fmt_temp(info.get("temp_max")),
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
    }


def _fmt_temp(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return str(round(f))


def fill_lines(fields, info: dict, tags: dict, now: datetime.datetime,
               lang: str = "en") -> list[str]:
    """模板行列表 -> 填好占位符的文本行(空行丢弃)。未知占位符原样保留。"""
    repl = build_repl(info, tags, now, lang)
    out = []
    for line in fields or []:
        s = str(line)
        for k, v in repl.items():
            s = s.replace("{" + k + "}", str(v))
        s = s.strip()
        if s:
            out.append(s)
    return out


# ---------- 字体 ----------

_FONT_CANDIDATES = [
    # CJK 优先(城市/节气/自定义话语可能是中文)
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:\\Windows\\Fonts\\msyh.ttc",
    "C:\\Windows\\Fonts\\simhei.ttf",
    # 纯西文兜底
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arial.ttf",
]


def find_font() -> str | None:
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    return None


# ---------- 布局(纯计算, 便于测试) ----------

def _char_em(ch: str) -> float:
    """字符宽度估算(em): CJK 全宽, 其余按半宽。仅用于挂件盒尺寸, 允许近似。"""
    if ord(ch) > 0x2E80 or ch in "℃·—…":
        return 1.0
    return 0.56


def _text_width(text: str, fontsize: int) -> int:
    return int(sum(_char_em(c) for c in text) * fontsize)


def layout(lines: list[str], img_w: int, img_h: int, wcfg: dict) -> dict:
    """计算挂件盒与每行文本的位置。返回 px 坐标, 供各后端共用。"""
    scale = max(0.1, min(3.0, float(wcfg.get("scale") or 0.3)))
    base = max(16, round(img_w / 34 * scale))
    title = round(base * 1.45)
    sizes = [title] + [base] * (len(lines) - 1)
    pad = round(base * 0.75)
    line_gap = round(base * 0.45)
    widths = [_text_width(s, sz) for s, sz in zip(lines, sizes)]
    heights = [round(sz * 1.18) for sz in sizes]
    box_w = min(img_w - 8, max(widths) + pad * 2)
    box_h = min(img_h - 8, sum(heights) + line_gap * (len(lines) - 1) + pad * 2)

    style = str(wcfg.get("style") or "glass").lower()
    if style == "banner":
        bx, by = 0, img_h - box_h
    else:
        # position 为挂件盒中心点(相对图片 0~1), 与文本宽度无关, 便于固定在角落
        pos = wcfg.get("position") or {}
        try:
            fx = min(1.0, max(0.0, float(pos.get("x", 0.94))))
            fy = min(1.0, max(0.0, float(pos.get("y", 0.08))))
        except (TypeError, ValueError):
            fx, fy = 0.94, 0.08
        bx = min(img_w - box_w, max(0, round(fx * img_w) - box_w // 2))
        by = min(img_h - box_h, max(0, round(fy * img_h) - box_h // 2))
    rows = []
    y = by + pad
    for s, sz, w, h in zip(lines, sizes, widths, heights):
        rows.append({"text": s, "x": bx + pad, "y": y, "fontsize": sz})
        y += h + line_gap
    return {"box": [bx, by, box_w, box_h], "pad": pad, "rows": rows}


# ---------- ffmpeg 后端 ----------

def _fesc(path) -> str:
    """ffmpeg filter 参数转义(路径): 反斜杠与冒号。"""
    s = str(path)
    return s.replace("\\", "\\\\").replace(":", "\\:")


def _drawtext(row: dict, font: str, tf: str, minimal: bool) -> str:
    parts = [f"drawtext=fontfile={_fesc(font)}",
             f"textfile={_fesc(tf)}",
             f"fontsize={row['fontsize']}",
             "fontcolor=white@0.96",
             f"x={row['x']}", f"y={row['y']}",
             "expansion=none"]
    if minimal:
        parts += ["shadowcolor=black@0.55", "shadowx=2", "shadowy=2"]
    return ":".join(parts)


def _ffargs(lay: dict, wcfg: dict, font: str, tdir: Path, img_w: int) -> list[str]:
    style = str(wcfg.get("style") or "glass").lower()
    try:
        op = min(0.95, max(0.0, float(wcfg.get("bg_opacity", 0.55))))
    except (TypeError, ValueError):
        op = 0.55
    bx, by, bw, bh = lay["box"]
    texts = []
    for i, row in enumerate(lay["rows"]):
        tf = tdir / f"line{i}.txt"
        tf.write_text(row["text"], encoding="utf-8")
        texts.append(tf)
    minimal = style == "minimal"
    dt = ",".join(_drawtext(row, font, texts[i], minimal)
                  for i, row in enumerate(lay["rows"]))

    if minimal:  # 无背景, 仅阴影文字
        return ["-vf", dt]
    if style == "banner":
        box = (f"drawbox=x=0:y={by}:w={img_w}:h={bh}:color=black@{op}:t=fill")
        return ["-vf", f"{box},{dt}"]
    # glass / card: 圆角不可得, 用半透明盒+细边框; glass 再叠背景模糊
    border = f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=white@0.22:t=3"
    if style == "glass":
        blur_r = max(4, lay["pad"] // 2)
        fc = (f"[0:v]split=2[bg][fg];"
              f"[bg]crop={bw}:{bh}:{bx}:{by},boxblur={blur_r}[bl];"
              f"[fg][bl]overlay={bx}:{by}[comp];"
              f"[comp]drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=black@{round(op * 0.45, 2)}:t=fill,"
              f"{border},{dt}[vout]")
        return ["-filter_complex", fc, "-map", "[vout]"]
    box = f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=black@{op}:t=fill"
    return ["-vf", f"{box},{border},{dt}"]


def _probe_size(data: bytes) -> tuple[int, int]:
    """解析图片尺寸: PNG/JPEG 纯标准库; 其余格式回落 ffprobe。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":  # JPEG: 扫 SOF0/SOF1/SOF2 段
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                            "-show_streams", "-"], input=data, capture_output=True, timeout=20)
        for st in json.loads(r.stdout or "{}").get("streams", []):
            if st.get("width") and st.get("height"):
                return int(st["width"]), int(st["height"])
    except Exception as e:  # noqa: BLE001
        raise WidgetError(f"无法解析图片尺寸: {e}") from e
    raise WidgetError("无法解析图片尺寸")


def compose(data: bytes, wcfg: dict, info: dict, tags: dict,
            now: datetime.datetime, lang: str = "en") -> tuple[bytes, str]:
    """主入口: 壁纸 bytes -> 合成挂件后的 (jpeg bytes, "jpg")。"""
    if not shutil.which("ffmpeg"):
        raise WidgetError("未找到 ffmpeg, 无法合成挂件")
    lines = fill_lines(wcfg.get("fields"), info, tags, now, lang)
    if not lines:
        raise WidgetError("挂件内容为空")
    font = find_font()
    if font is None:
        raise WidgetError("未找到可用字体文件")

    img_w, img_h = _probe_size(data)
    lay = layout(lines, img_w, img_h, wcfg)
    with tempfile.TemporaryDirectory(prefix="weatherwall-wg-") as td:
        tdir = Path(td)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", "-", *(_ffargs(lay, wcfg, font, tdir, img_w)),
               "-frames:v", "1", "-q:v", "2", str(tdir / "out.jpg")]
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise WidgetError("ffmpeg 合成超时") from e
        out = tdir / "out.jpg"
        if r.returncode != 0 or not out.exists():
            raise WidgetError(f"ffmpeg 合成失败: {r.stderr.decode('utf-8', 'replace')[:200]}")
        return out.read_bytes(), "jpg"
