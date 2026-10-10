"""Windows 打包入口 (PyInstaller)。

双击启动默认 GUI 模式: 后台服务 + 原生 WebView2 窗口展示设置页。
构建: pyinstaller --onefile --windowed --name WeatherDynamic --icon assets/icon.ico winmain.py
"""

import sys

from weatherwall.__main__ import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("gui")
    sys.exit(main())
