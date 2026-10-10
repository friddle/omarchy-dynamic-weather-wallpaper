// WeatherDynamicWallpaper 设置窗口助手: 原生 WKWebView 窗口展示设置后台页面。
// 用法: WeatherDynamicWallpaperWindow <url>   (默认 http://127.0.0.1:8765)
// 构建: swiftc -O -framework Cocoa -framework WebKit mac_window.swift -o WeatherDynamicWallpaperWindow

import Cocoa
import WebKit

let urlStr = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8765"

// WKWebView 默认不弹文件选择面板, 必须实现 runOpenPanelWith,
// 否则页面里的 <input type=file>/点击上传会静默无反应。
final class PanelUIDelegate: NSObject, WKUIDelegate {
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedFileTypes = ["jpg", "jpeg", "png", "webp"]
        if panel.runModal() == .OK, let url = panel.url {
            completionHandler([url])
        } else {
            completionHandler(nil)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    let uiDelegate = PanelUIDelegate()

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 880),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "WeatherDynamicWallpaper"
        window.titlebarAppearsTransparent = false
        window.center()
        window.minSize = NSSize(width: 920, height: 700)

        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.uiDelegate = uiDelegate
        webView.underPageBackgroundColor = NSColor(calibratedRed: 0.06, green: 0.07, blue: 0.09, alpha: 1)
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)

        if let url = URL(string: urlStr) {
            webView.load(URLRequest(url: url))
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true  // 关窗即退出助手进程(后台服务由主程序维持)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
