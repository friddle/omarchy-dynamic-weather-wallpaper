"""GUI 窗口：用系统原生 WebView 展示设置后台页面。

优先 pywebview(Windows: WebView2 / macOS: WKWebView)；未安装或初始化失败时
回落到系统默认浏览器打开，并保持进程驻留(后台服务继续运行)。
"""

import threading
import time
import webbrowser

WINDOW_TITLE = "WeatherDynamic"
BG_COLOR = "#0f1117"


def _park() -> None:
    """GUI 不可用时驻留进程，保持后台服务运行。"""
    while True:
        time.sleep(3600)


def open_url(url: str) -> None:
    """尽力打开界面：原生窗口 -> 默认浏览器。阻塞直到窗口关闭(或驻留)。"""
    try:
        import webview  # pywebview

        def _on_loaded():
            pass

        webview.create_window(
            WINDOW_TITLE, url,
            width=1180, height=880, min_size=(920, 700),
            background_color=BG_COLOR,
        )
        webview.start()
        return
    except Exception as e:  # noqa: BLE001 - 任意失败回落浏览器
        print(f"pywebview 不可用({e})，回落系统浏览器", flush=True)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    _park()


def open_url_async(url: str) -> threading.Thread:
    t = threading.Thread(target=open_url, args=(url,), daemon=True, name="weatherwall-gui")
    t.start()
    return t
