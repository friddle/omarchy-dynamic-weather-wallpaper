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

  readonly property int pollIntervalSec: (settings && settings.pollIntervalSec >= 15) ? Math.floor(settings.pollIntervalSec) : 120
  readonly property bool showCity: settings ? settings.showCity === true : false

  readonly property string pluginDir: (Quickshell.env("HOME") || "") + "/.config/omarchy/plugins/" + moduleName
  readonly property string serverUrl: "http://127.0.0.1:8765"

  property var status: null
  property bool online: false

  readonly property var weather: (status && status.state && status.state.last_weather) ? status.state.last_weather : null
  readonly property string tag: weather ? String(weather.tag || "") : ""
  readonly property real temp: (weather && weather.temp_current !== undefined) ? Number(weather.temp_current) : NaN

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
    opacity: root.online ? 1.0 : 0.45

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.openControlPanel()
      else if (buttonCode === Qt.RightButton) root.serviceAction()
    }
  }
}
