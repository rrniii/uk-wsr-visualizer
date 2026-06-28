import SwiftUI

@main
struct UKWSRVisualizerMacApp: App {
    @StateObject private var server = ServerController()

    init() {
        if CommandLine.arguments.contains("--self-test") {
            let exitCode = SelfTest.run()
            Foundation.exit(exitCode)
        }
    }

    var body: some Scene {
        WindowGroup {
            AppShell(server: server)
                .frame(minWidth: 1100, minHeight: 720)
                .onAppear {
                    server.start()
                }
                .onDisappear {
                    server.stop()
                }
        }
        .windowStyle(.titleBar)
        .commands {
            CommandMenu("UK WSR Visualizer") {
                Button("Open Logs") {
                    server.openLog()
                }
                .keyboardShortcut("l", modifiers: [.command, .shift])

                Button("Clear Raw Cache") {
                    server.clearRawCache()
                }
                .keyboardShortcut("k", modifiers: [.command, .shift])

                Button("Reload Viewer") {
                    server.reloadViewer()
                }
                .keyboardShortcut("r", modifiers: [.command])
            }
        }
    }
}
