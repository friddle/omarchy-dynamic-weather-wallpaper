#!/usr/bin/env bash
# WeatherDynamic 打包:
#   ./build-mac.sh            构建 dist/WeatherDynamic.app
#   ./build-mac.sh dmg        构建 .app + 标准安装 DMG (dist/WeatherDynamic-<ver>.dmg)
#   ./build-mac.sh install    .app 拷贝到 /Applications + LaunchAgent(登录自启)
#   ./build-mac.sh release    打 tag 并创建 GitHub Release(附 DMG), 需已配置 remote
#   ./build-mac.sh uninstall  停止自启动并删除本机安装
#
# 签名: 自动探测 "Developer ID Application" 证书; 有则正式签名(可分发),
#       无则 ad-hoc 签名(仅本机可直开, 他人首次需右键->打开)。
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="WeatherDynamic"
BUNDLE_ID="com.friddle.weatherdynamic"
VERSION="$(python3 -c 'from weatherwall import __version__; print(__version__)')"
APP="dist/$APP_NAME.app"
DMG="dist/${APP_NAME}-${VERSION}.dmg"
AGENT_PLIST="$HOME/Library/LaunchAgents/$BUNDLE_ID.plist"
INSTALL_APP="/Applications/$APP_NAME.app"
SIGN_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | grep -m1 -o '"Developer ID Application[^"]*"' | tr -d '"' || true)"

# ---------- 图标: assets/icon.svg -> AppIcon.icns ----------
gen_icon() {
  local icns="assets/AppIcon.icns"
  if [ -f "$icns" ]; then return 0; fi
  echo "生成应用图标 icns..."
  local tmp png
  tmp="$(mktemp -d)"
  qlmanage -t -s 1024 -o "$tmp" assets/icon.svg >/dev/null 2>&1
  png="$tmp/icon.svg.png"
  [ -f "$png" ] || { echo "SVG 渲染失败(qlmanage), 请手动放置 assets/AppIcon.icns"; exit 1; }
  local iconset="$tmp/AppIcon.iconset"
  mkdir -p "$iconset"
  local size
  for size in 16 32 128 256 512; do
    sips -z $size $size "$png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    sips -z $((size*2)) $((size*2)) "$png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$iconset" -o "$icns"
  rm -rf "$tmp"
  echo "图标已生成: $icns"
}

# ---------- 构建与签名 ----------
build() {
  gen_icon
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  rsync -a --exclude '__pycache__' --exclude '*.pyc' weatherwall/ "$APP/Contents/Resources/weatherwall/"
  cp assets/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

  # 原生 Swift/WKWebView 设置窗口助手(确定性弹窗, 不依赖 pywebview)
  if command -v swiftc >/dev/null 2>&1; then
    swiftc -O -framework Cocoa -framework WebKit \
      assets/mac_window.swift -o "$APP/Contents/MacOS/WeatherDynamicWindow" 2>/dev/null \
      && echo "已编译原生窗口助手 WeatherDynamicWindow" \
      || echo "警告: Swift 编译失败, 双击将回退 pywebview/错误提示"
  else
    echo "警告: 未找到 swiftc(需 Xcode), 无原生窗口助手"
  fi

  cat > "$APP/Contents/MacOS/$APP_NAME" <<LAUNCHER
#!/bin/bash
# WeatherDynamic 启动器: 双击=GUI(服务+设置窗口, 装有 pywebview 时原生窗口, 否则浏览器)
# LaunchAgent 自启动请带 "serve" 参数(无界面)
DIR="\$(cd "\$(dirname "\$0")/../Resources" && pwd)"
cd "\$DIR"
for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "\$PY" ] && exec "\$PY" -m weatherwall gui
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
  <key>CFBundleDisplayName</key><string>WeatherDynamic</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
  <key>NSBackgroundOnly</key><true/>
</dict>
</plist>
PLIST

  if [ -n "$SIGN_IDENTITY" ]; then
    echo "使用 Developer ID 签名: $SIGN_IDENTITY"
    codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
  else
    echo "未找到 Developer ID Application 证书, 使用 ad-hoc 签名(本机可直开; 他人首次需右键->打开)"
    codesign --force --sign - "$APP"
  fi
  codesign --verify --verbose=1 "$APP" >/dev/null 2>&1 && echo "构建完成: $APP (v$VERSION)"
}

# ---------- DMG ----------
build_dmg() {
  build
  rm -f "$DMG"
  local staging
  staging="$(mktemp -d)/dmg"
  mkdir -p "$staging"
  cp -R "$APP" "$staging/"
  ln -s /Applications "$staging/Applications"
  hdiutil create -volname "$APP_NAME" -srcfolder "$staging" -ov -format UDZO "$DMG" >/dev/null
  echo "DMG 已生成: $DMG ($(du -h "$DMG" | cut -f1))"
  shasum -a 256 "$DMG" | tee "dist/${APP_NAME}-${VERSION}.dmg.sha256"
}

# ---------- 本机安装(LaunchAgent) ----------
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
    <string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/weatherdynamic.log</string>
  <key>StandardErrorPath</key><string>/tmp/weatherdynamic.err.log</string>
</dict>
</plist>
AGENT
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
    echo "✓ 服务运行正常, 设置后台: http://127.0.0.1:8765  (日志: /tmp/weatherdynamic.log)"
  else
    echo "服务尚未就绪, 查看 /tmp/weatherdynamic.err.log"
  fi
}

cmd_uninstall() {
  launchctl bootout "gui/$(id -u)" "$AGENT_PLIST" 2>/dev/null || true
  rm -f "$AGENT_PLIST"
  rm -rf "$INSTALL_APP"
  echo "已停止自启动并删除 $INSTALL_APP (配置与壁纸缓存保留)"
}

# ---------- GitHub Release ----------
cmd_release() {
  local tag="v$VERSION"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "tag $tag 已存在"
  else
    git tag "$tag"
  fi
  [ -f "$DMG" ] || build_dmg
  local notes_file
  notes_file="$(mktemp)"
  cat > "$notes_file" <<NOTES
**WeatherDynamic v$VERSION** — dynamic weather wallpaper for macOS.

安装: 下载 DMG → 打开 → 将 WeatherDynamic 拖入 Applications → 双击运行(后台应用, 无 Dock 图标)。
设置后台: http://127.0.0.1:8765

- 安装后如需登录自启: 终端执行 \`./build-mac.sh install\` 或参考 README
- 天气与生图均支持免 Key 默认源; AI 生图可配置任意 OpenAI 兼容接口
NOTES
  git push origin main --tags 2>/dev/null || git push origin HEAD --tags
  gh release create "$tag" "$DMG" "$DMG.sha256" \
    --title "$APP_NAME $tag" \
    --notes-file "$notes_file"
  echo "Release 已创建: $tag"
  rm -f "$notes_file"
}

case "${1:-build}" in
  build) build ;;
  dmg) build_dmg ;;
  install) cmd_install ;;
  uninstall|remove) cmd_uninstall ;;
  release) cmd_release ;;
  *) echo "用法: $0 [build|dmg|install|uninstall|release]"; exit 1 ;;
esac
