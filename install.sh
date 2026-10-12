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

CONFIG_URL="http://127.0.0.1:8765"
TOKEN_FILE="$HOME/.config/omarchy-dynamic-wallpaper/token"
[ "$(uname)" = "Darwin" ] && TOKEN_FILE="$HOME/Library/Application Support/omarchy-dynamic-wallpaper/token"
# 令牌经 URL fragment(#t=) 带入, 不会发给服务器; token 文件仅本用户可读
CONFIG_TOKEN_URL="$CONFIG_URL/#t=$(cat "$TOKEN_FILE" 2>/dev/null || true)"

# 等设置后台就绪(最多 ~15s)，就绪后在默认浏览器弹出配置页
open_config_page() {
  if python3 - "$CONFIG_URL" <<'PY' 2>/dev/null
import sys, time, urllib.request
for _ in range(30):
    try:
        urllib.request.urlopen(sys.argv[1] + "/api/status", timeout=2)
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit(1)
PY
  then
    if [ "$(uname)" = "Darwin" ]; then
      open "$CONFIG_TOKEN_URL" >/dev/null 2>&1 || true
    else
      xdg-open "$CONFIG_TOKEN_URL" >/dev/null 2>&1 || true
    fi
    echo "已在浏览器打开配置页: $CONFIG_URL"
  else
    echo "配置页地址: $CONFIG_URL (服务暂未就绪，稍后手动打开; 打开后需输入一次本机令牌: $TOKEN_FILE)"
  fi
}

# 配置页说明
describe_config_page() {
  cat <<EOF
配置页说明 ($CONFIG_URL):
  ◉ 运行状态     运行日志、当前天气与标签；立即刷新 / 强制重新生图 / 测试天气
  🏞 基准图与 AI  上传或让 AI 生成基准图；填写 OpenAI 兼容生图 API (Base URL / Key / 模型 / Prompt 模板)
  ⚙ 详细配置     网络通道与代理、天气源与城市(IP 自动定位)、目标显示器、刷新间隔与命名规则、语言
  🗂 壁纸库      按基准图分组的成品壁纸，点击任意一张立即应用
EOF
}

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
  echo "设置后台: $CONFIG_URL  (日志: /tmp/weatherwall.log)"
  describe_config_page
  open_config_page

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
    describe_config_page
    open_config_page
  else
    echo "无 systemd，请在 Hyprland 配置加入:"
    echo "  exec-once = $SRC/run.sh serve"
    echo "配置页地址: $CONFIG_URL"
  fi

else
  echo "用法: ./install.sh [mac|linux|remove]  (mac 上默认 mac)"
  exit 1
fi
