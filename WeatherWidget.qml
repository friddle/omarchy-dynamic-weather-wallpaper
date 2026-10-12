import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.friddle.weatherwall"
  ipcTarget: "io.github.friddle.weatherwall"

  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color urgent: Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property int pollIntervalSec: (settings && settings.pollIntervalSec >= 15) ? Math.floor(settings.pollIntervalSec) : 120
  readonly property bool showCity: settings ? settings.showCity === true : false

  readonly property string pluginDir: (Quickshell.env("HOME") || "") + "/.config/omarchy/plugins/" + moduleName
  readonly property string serverUrl: "http://127.0.0.1:8765"
  // 图片端点需令牌(<img> 无法带 header, 经查询参数 ?t= 附带); token 文件仅本用户可读
  readonly property string token: tokenFile.text ? tokenFile.text.trim() : ""

  FileView {
    id: tokenFile
    path: (Quickshell.env("HOME") || "") + "/.config/omarchy-dynamic-wallpaper/token"
    blockLoading: false
    watchChanges: false
  }

  property var status: null
  property bool online: false

  readonly property var weather: (status && status.state && status.state.last_weather) ? status.state.last_weather : null
  readonly property string tag: weather ? String(weather.tag || "") : ""
  readonly property real temp: (weather && weather.temp_current !== undefined) ? Number(weather.temp_current) : NaN
  // 未配置生图 API 或基准图不存在时, 弹窗强引导去详细配置
  readonly property bool needsSetup: !online || !status || status.has_api_key !== true || status.base_image_exists !== true
  readonly property string baseImageName: (status && status.base_image) ? String(status.base_image) : ""

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function iconFor(tag) {
    switch (tag) {
      case "sunny": return "󰖙"
      case "partlycloudy": return "󰖕"
      case "cloudy": return "󰖐"
      case "overcast": return "󰖐"
      case "fog": return "󰖑"
      case "haze": return "󰼶"
      case "drizzle": return "󰖗"
      case "rain": return "󰖗"
      case "heavyrain": return "󰖘"
      case "snow": return "󰖜"
      case "thundershower": return "󰙾"
      case "wind": return "󰖞"
      default: return "󰖐"
    }
  }

  readonly property string barText: {
    if (!root.online) return ""
    var parts = [root.iconFor(root.tag)]
    if (!isNaN(root.temp)) parts.push(Math.round(root.temp) + "°")
    if (root.showCity && weather && weather.city) parts.push(String(weather.city))
    return parts.join(" ")
  }

  readonly property string tooltipTextValue: {
    if (!root.online) return "weatherwall offline · right-click to start"
    var w = root.weather
    if (!w) return "weatherwall running · no weather yet"
    var bits = []
    bits.push(String(w.desc || w.tag || ""))
    if (w.city) bits.push(String(w.city))
    if (!isNaN(root.temp)) bits.push(Number(root.temp).toFixed(1) + "°C")
    if (status && status.state && status.state.last_run)
      bits.push("updated " + String(status.state.last_run).replace("T", " "))
    return bits.join(" · ")
  }

  function refresh() {
    if (statusProc.running) return
    statusProc.running = true
  }

  function parseStatus(raw) {
    var text = String(raw || "").trim()
    if (text === "") {
      root.online = false
      return
    }
    try {
      var parsed = JSON.parse(text)
      if (parsed && typeof parsed === "object") {
        root.status = parsed
        root.online = true
        return
      }
    } catch (e) {
      console.warn(root.moduleName + ": invalid status payload", e)
    }
    root.online = false
  }

  function openControlPanel() {
    // 裸 URL: 页面自行经 /api/session-token(内核 UID 校验)获取令牌,
    // 令牌不出现在任何命令行参数(/proc/<pid>/cmdline)里
    Quickshell.execDetached(["xdg-open", root.serverUrl])
  }

  function serviceAction() {
    if (!root.online) {
      // Unit missing means the service was never installed; the repo ships
      // install.sh, so fall back to a visible install run.
      Quickshell.execDetached(["bash", "-c",
        "systemctl --user start weatherwall.service 2>/dev/null || " +
        "omarchy-launch-floating-terminal-with-presentation bash " + root.pluginDir + "/install.sh linux"])
    } else {
      Quickshell.execDetached(["systemctl", "--user", "restart", "weatherwall.service"])
    }
    restartProbe.restart()
  }

  Timer {
    interval: root.pollIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    id: restartProbe
    interval: 6000
    onTriggered: root.refresh()
  }

  Process {
    id: statusProc
    command: ["curl", "-sf", "--max-time", "4", root.serverUrl + "/api/status"]
    running: false

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.parseStatus(text)
    }

    onExited: function(exitCode) {
      if (exitCode !== 0) root.online = false
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barText
    fontSize: Style.bar.iconFont
    horizontalMargin: 3.5
    tooltipText: root.tooltipTextValue
    opacity: root.needsSetup ? 0.55 : 1.0

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
      else if (buttonCode === Qt.RightButton) root.serviceAction()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTextKey: function(text) { if (text === "r" || text === "R") root.refresh() }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height

        Column {
          id: contentColumn
          width: parent.width
          spacing: Style.space(10)

          // 天气状态
          Item {
            width: parent.width
            height: statusRow.implicitHeight

            Row {
              id: statusRow
              spacing: Style.space(8)

              Text {
                text: root.online ? root.iconFor(root.tag) : ""
                font.family: root.fontFamily
                font.pixelSize: Style.space(22)
                color: root.foreground
                anchors.verticalCenter: parent.verticalCenter
              }

              Column {
                spacing: Style.space(2)

                Text {
                  text: {
                    if (!root.online) return "weatherwall offline"
                    var w = root.weather
                    if (!w) return "waiting for first round…"
                    var s = String(w.desc || w.tag || "")
                    if (!isNaN(root.temp)) s += " · " + Number(root.temp).toFixed(1) + "°C"
                    return s
                  }
                  font.pixelSize: Style.space(13)
                  color: root.foreground
                }

                Text {
                  property string cityText: (root.weather && root.weather.city) ? String(root.weather.city) : ""
                  property string timeText: (root.status && root.status.state && root.status.state.last_run)
                    ? String(root.status.state.last_run).replace("T", " ") : ""
                  text: cityText && timeText ? cityText + " · " + timeText : (cityText || timeText || "—")
                  font.pixelSize: Style.space(11)
                  color: root.dim
                }
              }
            }
          }

          // 未配置警告: 强引导点击详细配置
          Rectangle {
            width: parent.width
            radius: Style.space(8)
            visible: root.needsSetup
            color: Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.22)
            border.color: root.urgent
            border.width: 1
            implicitHeight: setupLabel.implicitHeight + Style.space(16)

            Text {
              id: setupLabel
              anchors.fill: parent
              anchors.margins: Style.space(8)
              text: !root.online
                ? "Service offline — click to configure / install"
                : "API key or base image missing — click to finish setup"
              font.pixelSize: Style.space(11)
              color: root.foreground
              wrapMode: Text.WordWrap
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onPressed: { root.close(); root.openControlPanel() }
            }
          }

          // 基准图预览
          Rectangle {
            width: parent.width
            height: Style.space(110)
            radius: Style.space(8)
            color: "transparent"
            border.color: root.dim
            border.width: 1
            clip: true
            visible: root.online

            Image {
              anchors.fill: parent
              anchors.margins: Style.space(2)
              source: root.online && root.baseImageName !== ""
                ? root.serverUrl + "/api/base-image-file?name=" + root.baseImageName + "&t=" + root.token : ""
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              cache: false
            }

            Text {
              anchors.centerIn: parent
              visible: !root.baseImageName
              text: "no base image"
              font.pixelSize: Style.space(11)
              color: root.dim
            }
          }

          // 详细设置(居中主按钮)
          Rectangle {
            width: parent.width
            height: Style.space(38)
            radius: Style.space(8)
            color: root.needsSetup ? Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.35)
                                   : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
            border.color: root.needsSetup ? root.urgent : root.dim
            border.width: root.needsSetup ? 2 : 1
            anchors.horizontalCenter: parent.horizontalCenter

            Text {
              anchors.centerIn: parent
              text: "⚙  详细设置 · Detailed Settings"
              font.pixelSize: Style.space(13)
              color: root.foreground
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onPressed: { root.close(); root.openControlPanel() }
            }
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "left-click: panel · right-click: restart service · R: refresh"
            font.pixelSize: Style.space(9)
            color: root.dim
          }
        }
      }
    }
  }
}
