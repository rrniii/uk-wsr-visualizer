import Foundation
import UIKit

private struct VideoExportJobManifest: Codable {
    var id: String
    var signature: String
    var displayName: String
    var outputBaseName: String
    var requestedTimes: [String]
    var completedTimes: [String]
    var createdAt: Date
    var updatedAt: Date
}

struct VideoExportFrameEntry {
    var index: Int
    var time: String
    var url: URL
}

final class VideoExportFrameStore {
    private let directory: URL
    private let framesDirectory: URL
    private let manifestURL: URL
    private var manifest: VideoExportJobManifest

    var outputBaseName: String { manifest.outputBaseName }
    var requestedFrameCount: Int { manifest.requestedTimes.count }

    var completedTimes: Set<String> {
        let completed = Set(manifest.completedTimes)
        return Set(manifest.requestedTimes.enumerated().compactMap { index, time in
            guard completed.contains(time), FileManager.default.fileExists(atPath: frameURL(index: index, time: time).path) else {
                return nil
            }
            return time
        })
    }

    init(signature: String, displayName: String, outputBaseName: String, requestedTimes: [String]) throws {
        let id = Self.stableIdentifier(for: signature)
        let root = try PPIImageExporter.videoExportJobsDirectory()
        directory = root.appendingPathComponent(id, isDirectory: true)
        framesDirectory = directory.appendingPathComponent("frames", isDirectory: true)
        manifestURL = directory.appendingPathComponent("manifest.json")

        if let existing = Self.loadManifest(from: manifestURL),
           existing.signature == signature,
           existing.requestedTimes == requestedTimes {
            manifest = existing
            manifest.displayName = displayName
            manifest.outputBaseName = outputBaseName
        } else {
            try? FileManager.default.removeItem(at: directory)
            let now = Date()
            manifest = VideoExportJobManifest(
                id: id,
                signature: signature,
                displayName: displayName,
                outputBaseName: outputBaseName,
                requestedTimes: requestedTimes,
                completedTimes: [],
                createdAt: now,
                updatedAt: now
            )
        }

        try FileManager.default.createDirectory(at: framesDirectory, withIntermediateDirectories: true, attributes: nil)
        try saveManifest()
    }

    static func resumeStatus(signature: String, requestedTimes: [String]) -> (completed: Int, requested: Int)? {
        let id = stableIdentifier(for: signature)
        guard let root = try? PPIImageExporter.videoExportJobsDirectory() else { return nil }
        let directory = root.appendingPathComponent(id, isDirectory: true)
        let manifestURL = directory.appendingPathComponent("manifest.json")
        guard let manifest = loadManifest(from: manifestURL),
              manifest.signature == signature,
              manifest.requestedTimes == requestedTimes else {
            return nil
        }
        let framesDirectory = directory.appendingPathComponent("frames", isDirectory: true)
        let completed = Set(manifest.completedTimes)
        let frameCount = manifest.requestedTimes.enumerated().filter { index, time in
            completed.contains(time) &&
                FileManager.default.fileExists(atPath: frameURL(framesDirectory: framesDirectory, index: index, time: time).path)
        }.count
        guard frameCount > 0 else { return nil }
        return (frameCount, manifest.requestedTimes.count)
    }

    static func clear(signature: String) {
        let id = stableIdentifier(for: signature)
        guard let root = try? PPIImageExporter.videoExportJobsDirectory() else { return }
        let directory = root.appendingPathComponent(id, isDirectory: true)
        try? FileManager.default.removeItem(at: directory)
    }

    func saveFrame(image: UIImage, index: Int, time: String) throws {
        let destination = frameURL(index: index, time: time)
        guard let data = image.jpegData(compressionQuality: 0.92) ?? image.pngData() else {
            throw PPIImageExportError.noPNGData
        }
        try data.write(to: destination, options: .atomic)
        if !manifest.completedTimes.contains(time) {
            manifest.completedTimes.append(time)
        }
        manifest.updatedAt = Date()
        try saveManifest()
    }

    func availableFrameEntries() -> [VideoExportFrameEntry] {
        let completed = completedTimes
        return manifest.requestedTimes.enumerated().compactMap { index, time in
            guard completed.contains(time) else { return nil }
            let url = frameURL(index: index, time: time)
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
            return VideoExportFrameEntry(index: index, time: time, url: url)
        }
    }

    func clear() {
        try? FileManager.default.removeItem(at: directory)
    }

    private func frameURL(index: Int, time: String) -> URL {
        Self.frameURL(framesDirectory: framesDirectory, index: index, time: time)
    }

    private static func frameURL(framesDirectory: URL, index: Int, time: String) -> URL {
        framesDirectory
            .appendingPathComponent(String(format: "%05d-", index + 1) + safeFileComponent(time))
            .appendingPathExtension("jpg")
    }

    private func saveManifest() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        try data.write(to: manifestURL, options: .atomic)
    }

    private static func loadManifest(from url: URL) -> VideoExportJobManifest? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(VideoExportJobManifest.self, from: data)
    }

    static func safeFileComponent(_ raw: String) -> String {
        let value = raw
            .lowercased()
            .map { character -> Character in
                character.isLetter || character.isNumber || character == "-" ? character : "-"
            }
            .reduce(into: "") { output, character in
                output.append(character)
            }
        let collapsed = value.replacingOccurrences(of: "-+", with: "-", options: .regularExpression)
        return collapsed.trimmingCharacters(in: CharacterSet(charactersIn: "-")).isEmpty ?
            "uk-wsr-export" :
            String(collapsed.trimmingCharacters(in: CharacterSet(charactersIn: "-")).prefix(80))
    }

    private static func stableIdentifier(for value: String) -> String {
        var hash: UInt64 = 1469598103934665603
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 1099511628211
        }
        return String(hash, radix: 16)
    }
}
