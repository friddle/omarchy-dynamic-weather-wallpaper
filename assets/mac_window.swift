// WeatherDynamic 设置窗口助手: 原生 WKWebView 窗口展示设置后台页面。
// 用法: WeatherDynamicWindow <url>   (默认 http://127.0.0.1:8765)
// 构建: swiftc -O -framework Cocoa -framework WebKit mac_window.swift -o WeatherDynamicWindow

import Cocoa
import WebKit

let urlStr = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8765"

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 880),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "WeatherDynamic"
        window.titlebarAppearsTransparent = false
        window.center()
        window.minSize = NSSize(width: 920, height: 700)

        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
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
