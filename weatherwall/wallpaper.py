"""壁纸切换：macOS 优先，Windows/Linux(Omarchy-Hyprland) 兼容。支持多显示器选择。

macOS   : osascript System Events (按 desktop 序号可指定单个显示器/空间)
Windows : PowerShell SystemParametersInfo(SPI_SETDESKWALLPAPER) — 单显示器
Linux   : omarchy(Omarchy 背景, 系统级联动) -> swww(Hyprland, -o 指定输出)
          -> hyprpaper -> gsettings -> feh；每一步都检查结果，失败继续回落

displays 参数: "all"(默认) 或 序号列表 [1,3] (对应 /api/displays 返回的 index)
omarchy/swww 之外注意: Omarchy 系统背景机制作用于全部显示器，不支持按序号选择。
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


class WallpaperError(Exception):
    pass


def _run(cmd: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------- 显示器枚举 ----------

def _list_displays_macos() -> list[dict]:
    script = (
        'tell application "System Events"\n'
        'set out to ""\n'
        'repeat with i from 1 to count of desktops\n'
        'set pn to picture of desktop i\n'
        'set out to out & i & "|" & (display name of desktop i) & "|" & (pn as string) & linefeed\n'
        'end repeat\n'
        'return out\n'
        'end tell'
    )
    r = _run(["osascript", "-e", script])
    if r.returncode != 0:
        raise WallpaperError("枚举显示器失败: " + r.stderr.strip()[:150])
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        out.append({"index": int(parts[0]), "name": parts[1],
                    "picture": "" if "missing value" in parts[2] else parts[2]})
    return out


def _list_displays_linux() -> list[dict]:
    if shutil.which("hyprctl"):
        try:
            r = _run(["hyprctl", "-j", "monitors"])
            out = []
            for i, m in enumerate(json.loads(r.stdout or "[]"), 1):
                out.append({"index": i, "name": m.get("name", str(i)), "picture": ""})
            if out:
                return out
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if shutil.which("xrandr"):
        r = _run(["xrandr", "--query"])
        out = []
        for i, line in enumerate(r.stdout.splitlines(), 0):
            if " connected" in line:
                out.append({"index": len(out) + 1, "name": line.split(" connected")[0].strip(),
                            "picture": ""})
        if out:
            return out
    return [{"index": 1, "name": "Default", "picture": ""}]


def list_displays() -> list[dict]:
    try:
        if sys.platform == "darwin":
            return _list_displays_macos()
        if sys.platform.startswith("win") or sys.platform == "cygwin":
            return [{"index": 1, "name": "Default", "picture": ""}]
        return _list_displays_linux()
    except Exception as e:  # noqa: BLE001 - 枚举失败不影响主流程
        raise WallpaperError(str(e)) from e


def display_resolution() -> tuple[int, int] | None:
    """主显示器(分辨率最高那块)的像素分辨率; 检测失败返回 None。"""
    if shutil.which("hyprctl"):
        try:
            mons = json.loads(_run(["hyprctl", "-j", "monitors"]).stdout or "[]")
            if mons:
                m = max(mons, key=lambda d: int(d.get("width", 0)) * int(d.get("height", 0)))
                w, h = int(m.get("width", 0)), int(m.get("height", 0))
                if w > 0 and h > 0:
                    return w, h
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if shutil.which("xrandr"):
        try:
            import re
            r = _run(["xrandr", "--current"])
            for line in r.stdout.splitlines():
                if " connected" in line and "*" in line:
                    m = re.search(r"(\d+)x(\d+)\s+\d+\.\d+\*", line)
                    if m:
                        return int(m.group(1)), int(m.group(2))
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


# ---------- 壁纸设置 ----------

def _norm_displays(displays) -> list[int]:
    """displays 配置 -> 序号列表; "all"/None/空 返回 [] 表示全部。"""
    if displays in (None, "all", "", [], "[]"):
        return []
    if isinstance(displays, str):
        displays = [d.strip() for d in displays.split(",") if d.strip()]
    out = []
    for d in displays:
        try:
            n = int(d)
            if n not in out:
                out.append(n)
        except (TypeError, ValueError):
            continue
    return out


def _set_macos(path: Path, indices: list[int]) -> None:
    p = str(path.resolve())
    if not indices:
        apple = (f'tell application "System Events" to tell every desktop '
                 f'to set picture to POSIX file "{p}"')
        try:
            if _run(["osascript", "-e", apple]).returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        finder = f'tell application "Finder" to set desktop picture to POSIX file "{p}"'
        try:
            r = _run(["osascript", "-e", finder])
            if r.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise WallpaperError("osascript 设置壁纸失败(可能需要授予自动化权限)")
    errors = []
    for i in indices:
        script = (f'tell application "System Events" to tell desktop {int(i)} '
                  f'to set picture to POSIX file "{p}"')
        try:
            r = _run(["osascript", "-e", script])
            if r.returncode != 0:
                errors.append(f"desktop {i}: {r.stderr.strip()[:80]}")
        except (OSError, subprocess.TimeoutExpired) as e:
            errors.append(f"desktop {i}: {e}")
    if errors:
        raise WallpaperError("; ".join(errors))


def _set_windows(path: Path) -> None:
    p = str(path.resolve())
    ps = (
        "$code = @'\n"
        "using System.Runtime.InteropServices;\n"
        "public class W { [DllImport(\"user32.dll\", SetLastError=true)] "
        "public static extern bool SystemParametersInfo(int a, int b, string c, int d); }\n"
        "'@\n"
        "Add-Type -TypeDefinition $code\n"
        f"[W]::SystemParametersInfo(20, 0, \"{p}\", 3) | Out-Null"
    )
    try:
        r = _run(["powershell", "-NoProfile", "-Command", ps], timeout=30)
        if r.returncode == 0:
            return
        raise WallpaperError(r.stderr.strip()[:200] or "powershell 返回非零")
    except OSError as e:
        raise WallpaperError(f"调用 powershell 失败: {e}") from e


def _linux_output_names(indices: list[int]) -> list[str]:
    try:
        r = _run(["hyprctl", "-j", "monitors"])
        mons = json.loads(r.stdout or "[]")
        return [mons[i - 1]["name"] for i in indices if 0 < i <= len(mons)]
    except Exception:  # noqa: BLE001
        return []


def _set_linux(path: Path, indices: list[int]) -> None:
    p = str(path.resolve())
    # Omarchy: 走系统背景机制(更新 current/background 软链并通知 shell 插件),
    # 与主题切换/时间壁纸联动；系统级生效于全部显示器
    if shutil.which("omarchy"):
        r = _run(["omarchy", "theme", "bg", "set", p])
        if r.returncode == 0:
            return
    if shutil.which("swww"):
        cmd = ["swww", "img", p, "--transition-type", "grow", "--transition-duration", "1.5"]
        outputs = _linux_output_names(indices) if indices else []
        if len(outputs) == 1:
            r = _run(cmd + ["-o", outputs[0]])
        else:  # 全部或多个输出: swww 默认作用于全部
            r = _run(cmd)
        if r.returncode == 0:
            return
    # hyprpaper 未运行时 hyprctl 会返回非零，必须检查而不是盲改后直接返回
    if shutil.which("hyprctl") and shutil.which("hyprpaper"):
        try:
            preload = _run(["hyprctl", "hyprpaper", "preload", p])
            mons = json.loads(_run(["hyprctl", "-j", "monitors"]).stdout or "[]")
            targets = [m["name"] for m in mons if not indices or m.get("id", -1) + 1 in indices
                       or mons.index(m) + 1 in indices]
            if preload.returncode == 0 and targets and all(
                    _run(["hyprctl", "hyprpaper", "wallpaper", f"{name},{p}"]).returncode == 0
                    for name in targets):
                return
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    if shutil.which("gsettings"):
        uri = "file://" + p
        r1 = _run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri])
        r2 = _run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri])
        if r1.returncode == 0 and r2.returncode == 0:
            return
    if shutil.which("feh"):
        r = _run(["feh", "--bg-fill", p])
        if r.returncode == 0:
            return
    raise WallpaperError("壁纸设置失败: 未找到可用的壁纸工具 (omarchy/swww/hyprpaper/gsettings/feh) 或全部执行失败")


def set_wallpaper(path: Path, displays=None) -> None:
    if not path.exists():
        raise WallpaperError(f"壁纸文件不存在: {path}")
    indices = _norm_displays(displays)
    if sys.platform == "darwin":
        _set_macos(path, indices)
    elif sys.platform.startswith("win") or sys.platform == "cygwin":
        _set_windows(path)
    else:
        _set_linux(path, indices)
