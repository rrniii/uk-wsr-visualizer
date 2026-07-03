import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let server = ServerController()
    private var mainWindow: NSWindow?
    private var mainWindowController: NSWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        configureMenu()
        showMainWindow()
        server.start()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        server.stop()
    }

    func showMainWindow() {
        if let mainWindow {
            mainWindow.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let hostingController = NSHostingController(
            rootView: AppShell(server: server)
                .frame(minWidth: 1100, minHeight: 720)
                .accessibilityIdentifier("UKWSRVisualizerMainContent")
        )
        let window = AccessibleWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "UK WSR Visualizer"
        window.contentViewController = hostingController
        window.setAccessibilityIdentifier("UKWSRVisualizerMainWindow")
        window.setAccessibilityTitle("UK WSR Visualizer")
        window.contentView?.setAccessibilityIdentifier("UKWSRVisualizerMainContentView")
        window.contentView?.setAccessibilityLabel("UK WSR Visualizer main content")
        window.minSize = NSSize(width: 1100, height: 720)
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.managed, .participatesInCycle]
        window.setFrameAutosaveName("UKWSRVisualizerMainWindow")
        window.center()
        let windowController = NSWindowController(window: window)
        mainWindow = window
        mainWindowController = windowController
        windowController.showWindow(nil)
        window.makeMain()
        NSApp.activate(ignoringOtherApps: true)
    }

    private func configureMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "About UK WSR Visualizer", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: ""))
        appMenu.addItem(.separator())
        appMenu.addItem(NSMenuItem(title: "Quit UK WSR Visualizer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let actionsMenuItem = NSMenuItem()
        let actionsMenu = NSMenu(title: "UK WSR Visualizer")
        actionsMenu.addItem(NSMenuItem(title: "Open Logs", action: #selector(openLogs(_:)), keyEquivalent: "L"))
        actionsMenu.addItem(NSMenuItem(title: "Clear Raw Cache", action: #selector(clearRawCache(_:)), keyEquivalent: "K"))
        actionsMenu.addItem(NSMenuItem(title: "Reload Viewer", action: #selector(reloadViewer(_:)), keyEquivalent: "r"))
        actionsMenuItem.submenu = actionsMenu
        mainMenu.addItem(actionsMenuItem)

        NSApp.mainMenu = mainMenu
    }

    @objc private func openLogs(_ sender: Any?) {
        server.openLog()
    }

    @objc private func clearRawCache(_ sender: Any?) {
        server.clearRawCache()
    }

    @objc private func reloadViewer(_ sender: Any?) {
        server.reloadViewer()
    }
}
