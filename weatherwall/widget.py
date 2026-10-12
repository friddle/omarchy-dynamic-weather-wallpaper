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

from .weather import weather_display, WEATHER_ICON
from .solarterm import solarterm_display, SOLARTERM_ICON


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
    """挂件模板可用占位符。{temp} 是当前温度(与 prompt 模板一致), 另加时间日期与图标。"""
    weather_icon = WEATHER_ICON.get(str(tags.get("weather") or ""), "")
    solarterm_icon = SOLARTERM_ICON.get(str(tags.get("solarterm") or ""), "")
    return {
        **tags,
        "weather_name": weather_display(tags["weather"], lang),
        "weather_en": weather_display(tags["weather"], "en"),
        "weather_cn": weather_display(tags["weather"], "zh"),
        "solarterm_name": solarterm_display(tags["solarterm"], lang),
        "solarterm_en": solarterm_display(tags["solarterm"], "en"),
        "solarterm_cn": solarterm_display(tags["solarterm"], "zh"),
        "weather_icon": weather_icon,
        "icon": weather_icon,  # 旧名兼容
        "solarterm_icon": solarterm_icon,
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


# ---------- 图标字体({icon} 行专用; 需覆盖天气符号字形) ----------

_ICON_FONT_CANDIDATES = [
    "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansSymbols2*.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2*.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2.ttf",
    "C:\\Windows\\Fonts\\seguisym.ttf",       # Windows: Segoe UI Symbol
    "/System/Library/Fonts/Apple Symbols.ttf",  # macOS
    "/System/Library/Fonts/Symbol.ttf",
]


def font_covers(font: str, chars) -> bool:
    """字体 cmap 覆盖检查(TTC/TTF, 支持 cmap format 4/12), 纯标准库。"""
    try:
        data = Path(font).read_bytes()
    except OSError:
        return False
    if len(data) < 12:
        return False
    offs = [0]
    if data[:4] == b"ttcf" and len(data) >= 16:
        n = struct.unpack(">I", data[8:12])[0]
        offs = [struct.unpack(">I", data[12 + 4 * i:16 + 4 * i])[0]
                for i in range(min(n, 16)) if 16 + 4 * i <= len(data)]
    want = {ord(c) for c in chars}
    have: set[int] = set()
    for off in offs:
        try:
            if off + 6 > len(data):
                continue
            numTables = struct.unpack(">H", data[off + 4:off + 6])[0]
            for i in range(numTables):
                rec = off + 12 + 16 * i
                if rec + 16 > len(data) or data[rec:rec + 4] != b"cmap":
                    continue
                sub_off = struct.unpack(">I", data[rec + 8:rec + 12])[0]
                n = struct.unpack(">H", data[off + sub_off + 2:off + sub_off + 4])[0]
                for j in range(n):
                    _, _, oj = struct.unpack(">HHI",
                        data[off + sub_off + 4 + 8 * j:off + sub_off + 12 + 8 * j])
                    so = off + sub_off + oj
                    if so + 2 > len(data):
                        continue
                    fmt = struct.unpack(">H", data[so:so + 2])[0]
                    if fmt == 4:
                        segX2 = struct.unpack(">H", data[so + 6:so + 8])[0]
                        seg = segX2 // 2
                        if seg == 0 or so + 16 + 2 * segX2 > len(data):
                            continue
                        ends = struct.unpack(f">{seg}H", data[so + 14:so + 14 + segX2])
                        starts = struct.unpack(f">{seg}H", data[so + 16 + segX2:so + 16 + 2 * segX2])
                        for s, e in zip(starts, ends):
                            have.update(range(s, e + 1))
                    elif fmt == 12:
                        n12 = struct.unpack(">I", data[so + 12:so + 16])[0]
                        p = so + 16
                        for _ in range(n12):
                            if p + 12 > len(data):
                                break
                            s, e, _g = struct.unpack(">III", data[p:p + 12])
                            p += 12
                            have.update(range(s, e + 1))
        except (struct.error, IndexError):
            continue
    return want <= have


def find_icon_font(chars) -> str | None:
    """返回能覆盖全部所给字形的符号字体路径; 找不到返回 None。"""
    import glob as _glob
    seen: list[str] = []
    for cand in _ICON_FONT_CANDIDATES:
        for f in (_glob.glob(cand) or [cand]):
            if f not in seen:
                seen.append(f)
    for f in seen:
        if Path(f).exists() and font_covers(f, chars):
            return f
    return None


# ---------- 布局(纯计算, 便于测试) ----------

def _char_em(ch: str) -> float:
    """字符宽度估算(em): CJK 全宽, 其余按半宽。仅用于挂件盒尺寸, 允许近似。"""
    if ord(ch) > 0x2E80 or ch in "℃·—…":
        return 1.0
    return 0.56


def _text_width(text: str, fontsize: int) -> int:
    return int(sum(_char_em(c) for c in text) * fontsize)


def _split_runs(text: str, icon_glyphs: set) -> list[tuple[str, bool]]:
    """把一行按 图标字形/普通文字 切成连续段: [(text, is_icon)]。"""
    runs: list[list] = []
    for ch in text:
        is_icon = ch in icon_glyphs
        if runs and runs[-1][1] == is_icon:
            runs[-1][0] += ch
        else:
            runs.append([ch, is_icon])
    return [(t, i) for t, i in runs]


def layout(lines: list[str], img_w: int, img_h: int, wcfg: dict,
           icon_glyphs: set | None = None, icon_font: str | None = None) -> dict:
    """计算挂件盒与每行各文字/图标段的位置。返回 px 坐标, 供各后端共用。"""
    icon_glyphs = icon_glyphs or set()
    scale = max(0.1, min(3.0, float(wcfg.get("scale") or 0.3)))
    base = max(16, round(img_w / 34 * scale))
    title = round(base * 1.45)
    pad = round(base * 0.75)
    line_gap = round(base * 0.45)
    sizes = [title] + [base] * (len(lines) - 1)

    rows_runs = []
    widths = []
    for s, sz in zip(lines, sizes):
        runs = _split_runs(s, icon_glyphs) if icon_glyphs else [(s, False)]
        runs = [{"text": t, "is_icon": i,
                 "font": icon_font if (i and icon_font) else None} for t, i in runs]
        w = sum(round(len(r["text"]) * sz * 1.05) if r["is_icon"]
                else _text_width(r["text"], sz) for r in runs)
        rows_runs.append((s, sz, runs, w))
        widths.append(w)

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
    for (s, sz, runs, w), h in zip(rows_runs, heights):
        x = bx + pad
        for run in runs:
            run["x"] = x
            x += round(len(run["text"]) * sz * 1.05) if run["is_icon"] \
                else _text_width(run["text"], sz)
        rows.append({"text": s, "runs": runs, "x": bx + pad, "y": y, "fontsize": sz})
        y += h + line_gap
    return {"box": [bx, by, box_w, box_h], "pad": pad, "rows": rows}


# ---------- ffmpeg 后端 ----------

def _fesc(path) -> str:
    """ffmpeg filter 参数转义(路径): 反斜杠与冒号。"""
    s = str(path)
    return s.replace("\\", "\\\\").replace(":", "\\:")


def _drawtext(row: dict, run: dict, font: str, tf: str, minimal: bool) -> str:
    use = run.get("font") or font
    parts = [f"drawtext=fontfile={_fesc(use)}",
             f"textfile={_fesc(tf)}",
             f"fontsize={row['fontsize']}",
             f"fontcolor={run.get('color', 'white@0.96')}",
             f"x={run['x']}", f"y={row['y']}",
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
    for row in lay["rows"]:
        for si, run in enumerate(row["runs"]):
            tf = tdir / f"line{row['y']}_{si}.txt"
            tf.write_text(run["text"], encoding="utf-8")
            texts.append((row, run, tf))
    minimal = style == "minimal"
    dt = ",".join(_drawtext(row, run, font, tf, minimal)
                  for row, run, tf in texts)

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
    # 图标字形({weather_icon}/{solarterm_icon}): 用符号字体渲染; 无字体则剔除
    icon_glyphs = set(WEATHER_ICON.values()) | set(SOLARTERM_ICON.values())
    used = {ch for ln in lines for ch in ln if ch in icon_glyphs}
    icon_font = find_icon_font(used) if used else None
    if used and icon_font is None:
        lines = ["".join(ch for ch in ln if ch not in icon_glyphs) for ln in lines]
        lines = [ln for ln in lines if ln.strip()]
        if not lines:
            raise WidgetError("挂件内容为空")
    lay = layout(lines, img_w, img_h, wcfg, icon_glyphs, icon_font)
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


# ---------- 日历挂件 ----------

HEART = "\u2665"  # 今日标记: 红心(需字体覆盖, 无则仅红字标注)

CAL_WEEKDAYS = {
    "en": ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"),
    "zh": ("一", "二", "三", "四", "五", "六", "日"),
}


def calendar_cells(now: datetime.datetime, lang: str = "en") -> dict:
    """月历数据(周一起始): 标题/表头/各周日期(0 为空位)。纯计算便于测试。"""
    import calendar as _cal
    weeks = _cal.Calendar(firstweekday=0).monthdayscalendar(now.year, now.month)
    is_zh = lang == "zh"
    title = f"{now.year}年{now.month}月" if is_zh else now.strftime("%B %Y")
    return {
        "title": title,
        "header": CAL_WEEKDAYS["zh"] if is_zh else CAL_WEEKDAYS["en"],
        "weeks": weeks,
        "lang": "zh" if is_zh else "en",
    }


def calendar_layout(img_w: int, img_h: int, ccfg: dict,
                    now: datetime.datetime, lang: str = "en") -> dict:
    """日历挂件盒与每个文本单元的 px 坐标。今日单元用红色, 其余白色。"""
    cal = calendar_cells(now, lang)
    scale = max(0.1, min(3.0, float(ccfg.get("scale") or 0.5)))
    base = max(14, round(img_w / 34 * scale))
    pad = round(base * 0.9)
    gap = round(base * 0.3)
    title_sz = round(base * 1.15)
    head_sz = round(base * 0.72)
    day_sz = base

    cw = _text_width("28", day_sz) + gap          # 列宽按两位数估
    rh = round(day_sz * 1.3)
    grid_w = cw * 7
    title_h = round(title_sz * 1.25)
    head_h = round(head_sz * 1.35)
    box_w = min(img_w - 8, grid_w + pad * 2)
    box_h = min(img_h - 8, title_h + head_h + rh * len(cal["weeks"]) + pad * 2 + gap)

    style = str(ccfg.get("style") or "glass").lower()
    if style == "banner":
        bx, by = 0, img_h - box_h
    else:
        # 与信息挂件一致: position 为挂件盒中心点(相对图片 0~1), 默认左侧垂直居中
        pos = ccfg.get("position") or {}
        try:
            fx = min(1.0, max(0.0, float(pos.get("x", 0.09))))
            fy = min(1.0, max(0.0, float(pos.get("y", 0.5))))
        except (TypeError, ValueError):
            fx, fy = 0.09, 0.5
        bx = min(img_w - box_w, max(0, round(fx * img_w) - box_w // 2))
        by = min(img_h - box_h, max(0, round(fy * img_h) - box_h // 2))

    def cell(col: int, y: float, text: str, sz: int, color: str) -> dict:
        return {"text": text, "x": bx + pad + col * cw, "y": round(y),
                "fontsize": sz, "color": color,
                "w": _text_width(text, sz), "center": True}

    cells = []
    y = float(by + pad)
    cells.append({**cell(0, y, cal["title"], title_sz, "white@0.97"), "center": False})
    y += title_h + gap
    for i, name in enumerate(cal["header"]):      # 周末列表头稍暗
        cells.append(cell(i, y, name, head_sz, "white@0.55" if i >= 5 else "white@0.75"))
    y += head_h + gap
    for week in cal["weeks"]:
        for i, d in enumerate(week):
            if d:
                cells.append(cell(i, y, str(d), day_sz,
                                  "0xff4d5e@0.98" if d == now.day else "white@0.96"))
        y += rh
    return {"box": [bx, by, box_w, box_h], "pad": pad, "cells": cells,
            "day_sz": day_sz, "gap": gap}


def _cal_ffargs(lay: dict, ccfg: dict, font: str, tdir: Path, img_w: int) -> list[str]:
    style = str(ccfg.get("style") or "glass").lower()
    try:
        op = min(0.95, max(0.0, float(ccfg.get("bg_opacity", 0.55))))
    except (TypeError, ValueError):
        op = 0.55
    bx, by, bw, bh = lay["box"]
    texts = []
    for i, c in enumerate(lay["cells"]):
        tf = tdir / f"cal{i}.txt"
        tf.write_text(c["text"], encoding="utf-8")
        texts.append((c, tf))
    minimal = style == "minimal"
    dt = ",".join(_drawtext(c, c, font, tf, minimal) for c, tf in texts)
    if minimal:  # 无背景, 仅阴影文字
        return ["-vf", dt]
    if style == "banner":  # 底部整幅横幅
        box = f"drawbox=x=0:y={by}:w={img_w}:h={bh}:color=black@{op}:t=fill"
        return ["-vf", f"{box},{dt}"]
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


def compose_calendar(data: bytes, ccfg: dict, now: datetime.datetime,
                     lang: str = "en") -> tuple[bytes, str]:
    """日历挂件主入口: 壁纸 bytes -> 合成月历后的 (jpeg bytes, "jpg")。今日红心标注。"""
    if not shutil.which("ffmpeg"):
        raise WidgetError("未找到 ffmpeg, 无法合成日历")
    font = find_font()
    if font is None:
        raise WidgetError("未找到可用字体文件")
    img_w, img_h = _probe_size(data)
    lay = calendar_layout(img_w, img_h, ccfg, now, lang)

    # 今日红心: 找得到覆盖 ♥ 的字体才画(数字左侧, 不挤占列宽); 否则仅红字标注
    heart_font = find_icon_font({HEART}) or (font if font_covers(font, HEART) else None)
    if heart_font:
        today = next((c for c in lay["cells"]
                      if c["color"].startswith("0xff4d5e") and c["text"] == str(now.day)), None)
        if today:
            heart_sz = round(lay["day_sz"] * 0.62)
            hx = today["x"] - round(heart_sz * 1.05)
            if hx < lay["box"][0] + lay["pad"] - round(lay["pad"] * 0.8):
                hx = today["x"]  # 兜底: 放不下就不偏移
            lay["cells"].append({"text": HEART, "x": hx,
                                 "y": today["y"] + round((lay["day_sz"] - heart_sz) * 0.35),
                                 "fontsize": heart_sz,
                                 "color": "0xff4d5e@0.98", "w": 0,
                                 "font": heart_font})

    with tempfile.TemporaryDirectory(prefix="weatherwall-cal-") as td:
        tdir = Path(td)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", "-", *(_cal_ffargs(lay, ccfg, font, tdir, img_w)),
               "-frames:v", "1", "-q:v", "2", str(tdir / "out.jpg")]
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise WidgetError("ffmpeg 日历合成超时") from e
        out = tdir / "out.jpg"
        if r.returncode != 0 or not out.exists():
            raise WidgetError(f"ffmpeg 日历合成失败: {r.stderr.decode('utf-8', 'replace')[:200]}")
        return out.read_bytes(), "jpg"
