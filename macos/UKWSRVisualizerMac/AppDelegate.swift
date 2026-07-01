import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let server = ServerController()

    private var mainWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        showMainWindow()
        server.start()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        server.stop()
    }

    private func showMainWindow() {
        if let window = mainWindow {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let content = AppShell(server: server)
            .frame(minWidth: 1100, minHeight: 720)
        let hostingController = NSHostingController(rootView: content)
        hostingController.view.setAccessibilityIdentifier("UKWSRVisualizerMainContent")

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "UK WSR Visualizer"
        window.contentViewController = hostingController
        window.minSize = NSSize(width: 1100, height: 720)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.collectionBehavior = [.managed, .participatesInCycle]
        window.setFrameAutosaveName("UKWSRVisualizerMainWindow")
        window.setAccessibilityRole(.window)
        window.setAccessibilitySubrole(.standardWindow)
        window.center()
        window.makeKeyAndOrderFront(nil)

        mainWindow = window
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        server.stop()
        NSApp.terminate(nil)
    }
}
