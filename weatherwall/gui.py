"""GUI 窗口：确定性地用原生 WebView 展示设置后台页面，绝不回落浏览器。

- macOS: 优先随包分发的原生 Swift/WKWebView 助手(WeatherDynamicWallpaperWindow)
- Windows / 其他: pywebview(Windows 打包时已内嵌, WebView2 Evergreen Win10/11 自带)
- 失败: 弹系统错误对话框说明原因，进程驻留保持后台服务
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOW_TITLE = "WeatherDynamicWallpaper"
WINDOW_SIZE = (1180, 880)


def _park() -> None:
    while True:
        time.sleep(3600)


def _mac_helper_path() -> str | None:
    """macOS .app 内置的 Swift WKWebView 窗口助手 (Contents/MacOS/WeatherDynamicWallpaperWindow)。"""
    exe = Path(__file__).resolve().parent.parent.parent / "MacOS" / "WeatherDynamicWallpaperWindow"
    return str(exe) if exe.exists() else None


def _error_dialog(msg: str) -> None:
    """尽力弹出系统级错误提示(不用浏览器)。"""
    print(f"[gui] {msg}", flush=True)
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, WINDOW_TITLE, 0x00000010)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e",
                            f'display dialog "{msg}" with title "{WINDOW_TITLE}" '
                            f'buttons {{"OK"}} default button "OK" with icon caution'],
                           timeout=120, capture_output=True)
        else:
            subprocess.run(["zenity", "--error", f"--title={WINDOW_TITLE}", f"--text={msg}"],
                           timeout=120, capture_output=True)
    except Exception:  # noqa: BLE001 - 对话框失败仅打日志
        pass


def open_url(url: str, token_path: str = "") -> None:
    """打开设置窗口，阻塞至窗口关闭(失败则提示并驻留进程)。

    token_path: 0600 令牌文件的"路径"(令牌本体不经 argv/URL):
      macOS 原生助手读取后经 WKUserScript 注入; Windows pywebview 加载后 evaluate_js 注入。
    """
    # 1) macOS 原生 Swift 助手
    if sys.platform == "darwin":
        helper = _mac_helper_path()
        if helper:
            try:
                subprocess.run([helper, url, token_path], check=False)
                return  # 窗口关闭 = 返回(服务由主进程维持)
            except OSError as e:
                _error_dialog(f"窗口助手启动失败: {e}\\n服务仍在后台运行: {url}")

    # 2) pywebview (Windows exe 内嵌)
    try:
        import json as _json

        import webview

        window = webview.create_window(
            WINDOW_TITLE, url,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=(920, 700),
            background_color="#0f1117",
        )

        def _inject_token():
            if token_path:
                try:
                    token = Path(token_path).read_text(encoding="utf-8").strip()
                    window.evaluate_js(
                        "try{sessionStorage.setItem('ww_token',"
                        + _json.dumps(token) + ")}catch(_){}")
                except OSError:
                    pass

        window.events.loaded += _inject_token
        webview.start()
        return
    except ImportError:
        _error_dialog(
            "未找到 WebView 组件(pywebview)。\\n\\n"
            "Windows 安装包已内置；源码运行请执行: pip install pywebview\\n"
            f"服务仍在后台运行: {url}"
        )
    except Exception as e:  # noqa: BLE001
        tip = ""
        if sys.platform == "win32" and "WebView2" in str(e):
            tip = "\\n\\n可能是缺少 WebView2 Runtime, 请安装:\\n"
            tip += "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
        _error_dialog(f"窗口创建失败: {e}{tip}\\n服务仍在后台运行: {url}")
    _park()


def open_url_async(url: str, token_path: str = "") -> threading.Thread:
    t = threading.Thread(target=open_url, args=(url, token_path), daemon=True,
                         name="weatherwall-gui")
    t.start()
    return t
