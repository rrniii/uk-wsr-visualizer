import AppKit
import Foundation

@MainActor
final class ServerController: ObservableObject {
    @Published var isReady = false
    @Published var hasFailed = false
    @Published var statusMessage = "Starting local radar viewer..."
    @Published var reloadToken = 0

    private var serverTask: Process?
    private var pollTask: Task<Void, Never>?
    private let timeoutSeconds: TimeInterval = 120

    let port: Int
    let appSupportURL: URL
    let logURL: URL
    let viewerURL: URL?

    init() {
        let environment = ProcessInfo.processInfo.environment
        port = Int(environment["UK_WSR_VISUALIZER_MAC_PORT"] ?? "") ?? 8765
        appSupportURL = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/UK WSR Visualizer", isDirectory: true)
        logURL = appSupportURL.appendingPathComponent("uk-wsr-visualizer.log")
        viewerURL = URL(string: "http://127.0.0.1:\(port)/?v=\(Self.buildVersion)")
    }

    var logoImage: NSImage? {
        if let url = Bundle.main.url(forResource: "UKWSRVisualizer", withExtension: "png") {
            return NSImage(contentsOf: url)
        }
        return nil
    }

    func start() {
        guard serverTask == nil else { return }
        guard let launcherURL = Bundle.main.url(forResource: "uk-wsr-visualizer-server", withExtension: "zsh") else {
            fail("Server launcher is missing from the app bundle.")
            return
        }
        guard FileManager.default.isExecutableFile(atPath: launcherURL.path) else {
            fail("Server launcher is not executable. Rebuild the Mac app.")
            return
        }

        do {
            try FileManager.default.createDirectory(at: appSupportURL, withIntermediateDirectories: true)
            appendLog("starting Xcode-managed Mac shell version \(Self.buildVersion) commit \(Self.gitCommit)")
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [launcherURL.path]
            process.environment = launchEnvironment()
            process.standardOutput = try appendHandle()
            process.standardError = process.standardOutput
            try process.run()
            serverTask = process
            appendLog("started server launcher pid \(process.processIdentifier) on port \(port)")
            pollForReady(startedAt: Date())
        } catch {
            fail("Unable to start the local server. Open the log for details.")
            appendLog("server launch failed: \(error.localizedDescription)")
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
        if let task = serverTask, task.isRunning {
            appendLog("stopping server launcher pid \(task.processIdentifier)")
            task.terminate()
        }
        serverTask = nil
    }

    func openLog() {
        NSWorkspace.shared.open(logURL)
    }

    func clearRawCache() {
        let cacheURL = appSupportURL
            .appendingPathComponent("data", isDirectory: true)
            .appendingPathComponent("remote-aggregate-cache", isDirectory: true)
        do {
            if FileManager.default.fileExists(atPath: cacheURL.path) {
                try FileManager.default.removeItem(at: cacheURL)
            }
            statusMessage = "Raw cache cleared."
            appendLog("cleared raw cache at \(cacheURL.path)")
        } catch {
            fail("Could not clear the raw cache. Open the log for details.")
            appendLog("clear raw cache failed: \(error.localizedDescription)")
        }
    }

    func reloadViewer() {
        reloadToken += 1
        statusMessage = "Reloading radar interface..."
    }

    private func pollForReady(startedAt: Date) {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if Date().timeIntervalSince(startedAt) > timeoutSeconds {
                    await MainActor.run {
                        self.fail("The local server did not become ready. Open the log for details.")
                    }
                    return
                }
                if await Self.ready(port: port) {
                    await MainActor.run {
                        self.isReady = true
                        self.hasFailed = false
                        self.statusMessage = "Radar interface loaded."
                    }
                    return
                }
                try? await Task.sleep(nanoseconds: 750_000_000)
            }
        }
    }

    private func launchEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        environment["UK_WSR_VISUALIZER_MAC_PORT"] = String(port)
        environment["UK_WSR_VISUALIZER_APP_VERSION"] = Self.buildVersion
        environment["UK_WSR_VISUALIZER_GIT_COMMIT"] = Self.gitCommit
        return environment
    }

    private func appendHandle() throws -> FileHandle {
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logURL)
        try handle.seekToEnd()
        return handle
    }

    private func appendLog(_ message: String) {
        do {
            try FileManager.default.createDirectory(at: appSupportURL, withIntermediateDirectories: true)
            let line = "\(Self.isoDateFormatter.string(from: Date())) \(message)\n"
            let handle = try appendHandle()
            if let data = line.data(using: .utf8) {
                try handle.write(contentsOf: data)
            }
            try handle.close()
        } catch {
            // Logging failures should not prevent the app from surfacing the main error.
        }
    }

    private func fail(_ message: String) {
        isReady = false
        hasFailed = true
        statusMessage = message
    }

    private static func ready(port: Int) async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/ready") else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private static var buildVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
    }

    private static var gitCommit: String {
        Bundle.main.object(forInfoDictionaryKey: "UKWSRGitCommit") as? String ?? "unknown"
    }

    private static let isoDateFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}

enum SelfTest {
    static func run() -> Int32 {
        let port = Int(ProcessInfo.processInfo.environment["UK_WSR_VISUALIZER_MAC_PORT"] ?? "") ?? 8765
        let appSupport = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/UK WSR Visualizer", isDirectory: true)
        let logURL = appSupport.appendingPathComponent("uk-wsr-visualizer.log")

        guard let launcherURL = Bundle.main.url(forResource: "uk-wsr-visualizer-server", withExtension: "zsh") else {
            print("{\"ready\":false,\"error\":\"missing server launcher\"}")
            return 2
        }

        do {
            try FileManager.default.createDirectory(at: appSupport, withIntermediateDirectories: true)
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [launcherURL.path]
            var environment = ProcessInfo.processInfo.environment
            environment["UK_WSR_VISUALIZER_MAC_PORT"] = String(port)
            process.environment = environment
            if !FileManager.default.fileExists(atPath: logURL.path) {
                FileManager.default.createFile(atPath: logURL.path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: logURL)
            try handle.seekToEnd()
            process.standardOutput = handle
            process.standardError = handle
            try process.run()
            defer {
                if process.isRunning {
                    process.terminate()
                }
            }
            let deadline = Date().addingTimeInterval(120)
            while Date() < deadline {
                if synchronousReady(port: port) {
                    print("{\"ready\":true,\"port\":\(port),\"log\":\"\(logURL.path)\"}")
                    return 0
                }
                Thread.sleep(forTimeInterval: 0.75)
            }
            print("{\"ready\":false,\"error\":\"timeout\",\"port\":\(port),\"log\":\"\(logURL.path)\"}")
            return 3
        } catch {
            print("{\"ready\":false,\"error\":\"\(error.localizedDescription)\"}")
            return 4
        }
    }

    private static func synchronousReady(port: Int) -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/ready") else { return false }
        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: url) { _, response, _ in
            if let http = response as? HTTPURLResponse {
                ok = (200..<300).contains(http.statusCode)
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 1.5)
        return ok
    }
}
