"""壁纸切换：macOS 优先，Windows/Linux(Omarchy-Hyprland) 兼容。

macOS   : osascript 设置所有桌面空间 (System Events, 失败回落 Finder)
Windows : PowerShell SystemParametersInfo(SPI_SETDESKWALLPAPER)
Linux   : swww(Hyprland 动态壁纸) -> hyprpaper -> gsettings(GNOME) -> feh
"""

import shutil
import subprocess
import sys
from pathlib import Path


class WallpaperError(Exception):
    pass


def _run(cmd: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _set_macos(path: Path) -> None:
    p = str(path.resolve())
    apple = f'tell application "System Events" to tell every desktop to set picture to POSIX file "{p}"'
    finder = f'tell application "Finder" to set desktop picture to POSIX file "{p}"'
    for script in (apple, finder):
        try:
            r = _run(["osascript", "-e", script])
            if r.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise WallpaperError("osascript 设置壁纸失败(可能需要授予自动化权限)")


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


def _set_linux(path: Path) -> None:
    p = str(path.resolve())
    # swww: Hyprland 生态常用
    if shutil.which("swww"):
        r = _run(["swww", "img", p, "--transition-type", "grow", "--transition-duration", "1.5"])
        if r.returncode == 0:
            return
    # hyprpaper: 通过 hyprctl 预加载并设置
    if shutil.which("hyprctl"):
        try:
            import json as _json
            _run(["hyprctl", "hyprpaper", "preload", p])
            r = _run(["hyprctl", "-j", "monitors"])
            for m in _json.loads(r.stdout or "[]"):
                name = m.get("name")
                if name:
                    _run(["hyprctl", "hyprpaper", "wallpaper", f"{name},{p}"])
            _run(["hyprctl", "hyprpaper", "unload", p])
            return
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    # GNOME
    if shutil.which("gsettings"):
        uri = "file://" + p
        _run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri])
        _run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri])
        return
    # X11 万金油
    if shutil.which("feh"):
        _run(["feh", "--bg-fill", p])
        return
    raise WallpaperError("未找到可用的壁纸工具 (swww/hyprpaper/gsettings/feh)")


def set_wallpaper(path: Path) -> None:
    if not path.exists():
        raise WallpaperError(f"壁纸文件不存在: {path}")
    if sys.platform == "darwin":
        _set_macos(path)
    elif sys.platform.startswith("win") or sys.platform == "cygwin":
        _set_windows(path)
    else:
        _set_linux(path)
