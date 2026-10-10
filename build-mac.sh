#!/usr/bin/env bash
# 打包并安装 macOS 应用:
#   ./build-mac.sh            构建 dist/WeatherWall.app
#   ./build-mac.sh install    构建 + 拷贝到 /Applications + 安装 LaunchAgent(登录自启/崩溃自动拉起)
#   ./build-mac.sh uninstall  停止并卸载自启动与应用
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="WeatherWall"
BUNDLE_ID="com.friddle.weatherwall"
VERSION="$(python3 -c 'from weatherwall import __version__; print(__version__)')"
APP="dist/$APP_NAME.app"
AGENT_PLIST="$HOME/Library/LaunchAgents/$BUNDLE_ID.plist"
INSTALL_APP="/Applications/$APP_NAME.app"

build() {
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  # 只带运行所需文件
  rsync -a --exclude '__pycache__' --exclude '*.pyc' weatherwall/ "$APP/Contents/Resources/weatherwall/"
  rm -rf "$APP/Contents/Resources/weatherwall/__pycache__"

  cat > "$APP/Contents/MacOS/$APP_NAME" <<LAUNCHER
#!/bin/bash
# WeatherWall 启动器: 设置后台(127.0.0.1:8765) + 壁纸调度循环
DIR="\$(cd "\$(dirname "\$0")/../Resources" && pwd)"
cd "\$DIR"
for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "\$PY" ] && exec "\$PY" -m weatherwall serve
done
echo "python3 not found (tried homebrew/local/system)" >&2
exit 1
LAUNCHER
  chmod +x "$APP/Contents/MacOS/$APP_NAME"

  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>Dynamic Weather Wallpaper</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

  codesign --force --sign - "$APP" >/dev/null 2>&1 || true
  echo "构建完成: $APP (v$VERSION)"
}

install_agent() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$AGENT_PLIST" <<AGENT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$BUNDLE_ID</string>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_APP/Contents/MacOS/$APP_NAME</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/weatherwall-app.log</string>
  <key>StandardErrorPath</key><string>/tmp/weatherwall-app.err.log</string>
</dict>
</plist>
AGENT
  # 若有旧的仓库版 agent(指向 run.sh)先停掉
  launchctl bootout "gui/$(id -u)" "$AGENT_PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENT_PLIST"
  sleep 1
  echo "LaunchAgent 已安装并启动(登录自启 + 崩溃自动拉起)"
}

cmd_install() {
  build
  rm -rf "$INSTALL_APP"
  cp -R "$APP" "$INSTALL_APP"
  echo "已安装到 $INSTALL_APP"
  install_agent
  sleep 1.5
  if curl -s -m 3 http://127.0.0.1:8765/api/status >/dev/null; then
    echo "✓ 服务运行正常, 设置后台: http://127.0.0.1:8765  (日志: /tmp/weatherwall-app.log)"
  else
    echo "服务尚未就绪, 查看 /tmp/weatherwall-app.err.log"
  fi
}

cmd_uninstall() {
  launchctl bootout "gui/$(id -u)" "$AGENT_PLIST" 2>/dev/null || true
  rm -f "$AGENT_PLIST"
  rm -rf "$INSTALL_APP"
  echo "已停止自启动并删除 $INSTALL_APP (配置与壁纸缓存保留)"
}

case "${1:-build}" in
  build) build ;;
  install) cmd_install ;;
  uninstall|remove) cmd_uninstall ;;
  *) echo "用法: $0 [build|install|uninstall]"; exit 1 ;;
esac
