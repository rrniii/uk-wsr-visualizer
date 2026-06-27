import SwiftUI
import WebKit

final class BrowserState: NSObject, ObservableObject {
    @Published var title = "UK WSR Visualizer"
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var canGoBack = false
    @Published var canGoForward = false

    var reload: (() -> Void)?
    var goBack: (() -> Void)?
    var goForward: (() -> Void)?
}

struct VisualizerWebView: UIViewRepresentable {
    let url: URL
    @ObservedObject var state: BrowserState

    func makeCoordinator() -> Coordinator {
        Coordinator(state: state)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never

        state.reload = { [weak webView] in
            webView?.reload()
        }
        state.goBack = { [weak webView] in
            webView?.goBack()
        }
        state.goForward = { [weak webView] in
            webView?.goForward()
        }

        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if webView.url == nil {
            webView.load(URLRequest(url: url))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        private let state: BrowserState

        init(state: BrowserState) {
            self.state = state
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            state.isLoading = true
            state.errorMessage = nil
            updateNavigationState(webView)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            state.isLoading = false
            state.title = webView.title?.isEmpty == false ? webView.title! : "UK WSR Visualizer"
            updateNavigationState(webView)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            state.isLoading = false
            state.errorMessage = error.localizedDescription
            updateNavigationState(webView)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            state.isLoading = false
            state.errorMessage = error.localizedDescription
            updateNavigationState(webView)
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if navigationAction.targetFrame == nil, let url = navigationAction.request.url {
                webView.load(URLRequest(url: url))
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if navigationAction.targetFrame == nil {
                webView.load(navigationAction.request)
            }
            return nil
        }

        private func updateNavigationState(_ webView: WKWebView) {
            state.canGoBack = webView.canGoBack
            state.canGoForward = webView.canGoForward
        }
    }
}
