// WeatherDynamicWallpaper 设置窗口助手: 原生 WKWebView 窗口展示设置后台页面。
// 用法: WeatherDynamicWallpaperWindow <url> [token文件路径]
//   第二个参数是 0600 的本机令牌文件路径(路径不敏感, 令牌本体不经 argv),
//   助手读取后用 WKUserScript 注入 sessionStorage —— 令牌不出现在 URL/页面请求里。
// 构建: swiftc -O -framework Cocoa -framework WebKit mac_window.swift -o WeatherDynamicWallpaperWindow

import Cocoa
import WebKit

let urlStr = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8765"
let tokenPath = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : ""

// WKWebView 默认不弹任何 JS 面板: 必须实现 runOpenPanelWith(文件上传)、
// alert/confirm/textInput(删除确认/重命名/新建模板名), 否则全部静默失败。
final class PanelUIDelegate: NSObject, WKUIDelegate {
    private func rootFor(_ webView: WKWebView) -> NSWindow? {
        webView.window
    }

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

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = prompt
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        input.stringValue = defaultText ?? ""
        alert.accessoryView = input
        let ok = alert.runModal() == .alertFirstButtonReturn
        completionHandler(ok ? input.stringValue : nil)
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
        // 注入本机令牌: 只有同用户的助手读得到 token 文件; 在任何页面脚本之前注入
        if !tokenPath.isEmpty, let raw = try? String(contentsOfFile: tokenPath, encoding: .utf8) {
            let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
                .replacingOccurrences(of: "\\", with: "\\\\")
                .replacingOccurrences(of: "'", with: "\\'")
            let script = WKUserScript(
                source: "try{sessionStorage.setItem('ww_token','\(token)')}catch(_){}",
                injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(script)
        }
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
