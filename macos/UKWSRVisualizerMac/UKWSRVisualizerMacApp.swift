import SwiftUI

@main
struct UKWSRVisualizerMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    init() {
        if CommandLine.arguments.contains("--self-test") {
            let exitCode = SelfTest.run()
            Foundation.exit(exitCode)
        }
    }

    var body: some Scene {
        Settings {
            EmptyView()
        }
        .commands {
            CommandMenu("UK WSR Visualizer") {
                Button("Open Logs") {
                    appDelegate.server.openLog()
                }
                .keyboardShortcut("l", modifiers: [.command, .shift])

                Button("Clear Raw Cache") {
                    appDelegate.server.clearRawCache()
                }
                .keyboardShortcut("k", modifiers: [.command, .shift])

                Button("Reload Viewer") {
                    appDelegate.server.reloadViewer()
                }
                .keyboardShortcut("r", modifiers: [.command])
            }
        }
    }
}
