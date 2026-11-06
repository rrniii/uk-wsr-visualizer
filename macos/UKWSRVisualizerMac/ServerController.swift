import AppKit
import Foundation
import Darwin

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
        appSupportURL = ServerLaunch.appSupportURL
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
        let launcherURL = ServerLaunch.executableURL
        guard FileManager.default.isExecutableFile(atPath: launcherURL.path) else {
            fail("Server launcher is not executable. Rebuild the Mac app.")
            return
        }

        do {
            try FileManager.default.createDirectory(at: appSupportURL, withIntermediateDirectories: true)
            appendLog("starting Xcode-managed Mac shell version \(Self.buildVersion) commit \(Self.gitCommit)")
            let process = Process()
            try ServerLaunch.configure(process, port: port)
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
                guard self.serverTask?.isRunning == true else {
                    self.fail("The local server stopped. Open the log for details.")
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
        let appSupport = ServerLaunch.appSupportURL
        let logURL = appSupport.appendingPathComponent("uk-wsr-visualizer.log")

                do {
            try FileManager.default.createDirectory(at: appSupport, withIntermediateDirectories: true)
            let process = Process()
            try ServerLaunch.configure(process, port: port)
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
                guard process.isRunning else {
                    print("{\"ready\":false,\"error\":\"server exited\"}")
                    return 5
                }
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


enum ServerLaunch {
    static var executableURL: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/UKWSRServer.app/Contents/MacOS/uk-wsr-visualizer-server")
    }

    static var appSupportURL: URL {
        if let path = ProcessInfo.processInfo.environment["UK_WSR_VISUALIZER_APP_SUPPORT"] {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/UK WSR Visualizer", isDirectory: true)
    }

    static func configure(_ process: Process, port: Int) throws {
        guard FileManager.default.isExecutableFile(atPath: executableURL.path) else {
            throw NSError(domain: "UKWSR", code: 2, userInfo: [NSLocalizedDescriptionKey: "The bundled server is missing. Reinstall the app."])
        }
        // Readiness must belong to this app, never an unrelated server on its port.
        guard port > 0, port <= 65535, portIsAvailable(port) else {
            throw NSError(domain: "UKWSR", code: 3, userInfo: [NSLocalizedDescriptionKey: "The local port is in use. Close the other viewer or choose another port."])
        }
        var environment = ProcessInfo.processInfo.environment
        for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"] {
            environment.removeValue(forKey: key)
        }
        let data = appSupportURL.appendingPathComponent("data", isDirectory: true)
        try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true)
        environment["UK_WSR_VISUALIZER_DATA_DIR"] = data.path
        environment["UK_WSR_VISUALIZER_CATALOG"] = data.appendingPathComponent("catalog.json").path
        environment["UK_WSR_VISUALIZER_GIT_SHA"] = Bundle.main.object(forInfoDictionaryKey: "UKWSRGitCommit") as? String
        process.executableURL = executableURL
        process.arguments = ["api", "--host", "127.0.0.1", "--port", String(port)]
        process.environment = environment
        process.currentDirectoryURL = appSupportURL
    }

    private static func portIsAvailable(_ port: Int) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return false }
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = UInt16(port).bigEndian
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}
