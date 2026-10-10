"""Windows 打包入口 (PyInstaller)。

无参数启动时默认执行 serve(设置后台 + 壁纸调度循环)。
构建: pyinstaller --onefile --windowed --name WeatherDynamic --icon assets/icon.ico winmain.py
"""

import sys

from weatherwall.__main__ import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    sys.exit(main())
