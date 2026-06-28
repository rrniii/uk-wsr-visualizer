import SwiftUI
import WebKit

struct WebContainer: NSViewRepresentable {
    let url: URL
    let reloadToken: Int

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.websiteDataStore = .nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        load(url, in: webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastReloadToken != reloadToken || webView.url == nil {
            context.coordinator.lastReloadToken = reloadToken
            load(url, in: webView)
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    private func load(_ url: URL, in webView: WKWebView) {
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        webView.load(request)
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var lastReloadToken = 0
    }
}
