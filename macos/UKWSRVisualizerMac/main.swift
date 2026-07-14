import AppKit

if CommandLine.arguments.contains("--self-test") {
    let exitCode = SelfTest.run()
    Foundation.exit(exitCode)
}

let app = NSApplication.shared
let delegate = MainActor.assumeIsolated {
    AppDelegate()
}
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
