#!/usr/bin/env bash
# 安装自启动:
#   ./install.sh mac     macOS   -> LaunchAgent (launchctl)
#   ./install.sh linux   Omarchy -> systemd 用户服务 (回落提示 Hyprland exec-once)
#   ./install.sh remove  卸载自启动
set -euo pipefail
cd "$(dirname "$0")"
SRC="$(pwd)"
ID="com.friddle.weatherwall"

command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
python3 -m weatherwall init

if [ "${1:-}" = "remove" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/$ID.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$ID.plist"
  else
    systemctl --user disable --now weatherwall.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/weatherwall.service"
  fi
  echo "已移除自启动"; exit 0
fi

if [ "$(uname)" = "Darwin" ] && [ "${1:-mac}" = "mac" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$HOME/Library/LaunchAgents/$ID.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$ID</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd '$SRC' && exec ./run.sh serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/weatherwall.log</string>
  <key>StandardErrorPath</key><string>/tmp/weatherwall.err.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/$ID.plist" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$ID.plist"
  echo "已安装 LaunchAgent 并启动: $ID"
  echo "设置后台: http://127.0.0.1:8765  (日志: /tmp/weatherwall.log)"

elif [ "${1:-}" = "linux" ]; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/weatherwall.service" <<EOF
[Unit]
Description=Dynamic weather wallpaper (omarchy)
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$SRC
ExecStart=$SRC/run.sh serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
  if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable --now weatherwall.service
    echo "已安装 systemd 用户服务并启动"
  else
    echo "无 systemd，请在 Hyprland 配置加入:"
    echo "  exec-once = $SRC/run.sh serve"
  fi
  echo "设置后台: http://127.0.0.1:8765"

else
  echo "用法: ./install.sh [mac|linux|remove]  (mac 上默认 mac)"
  exit 1
fi
