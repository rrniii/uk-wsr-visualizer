import CoreLocation
import Foundation
import MapKit
import OSLog
import UIKit

struct RadarCache {
    var rootDirectory: URL
    var fileManager: FileManager = .default

    static var live: RadarCache {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        return RadarCache(rootDirectory: caches.appendingPathComponent("RawHDF5", isDirectory: true))
    }

    func localAggregateURL(for item: CatalogItem) -> URL {
        rootDirectory
            .appendingPathComponent(item.radar, isDirectory: true)
            .appendingPathComponent(String(item.date.prefix(4)), isDirectory: true)
            .appendingPathComponent(item.objectKey.split(separator: "/").last.map(String.init) ?? "\(item.id).h5")
    }

    func localVolumeURL(for item: CatalogItem, volume: RawVolumeRecord) -> URL {
        rootDirectory
            .appendingPathComponent(item.radar, isDirectory: true)
            .appendingPathComponent(String(item.date.prefix(4)), isDirectory: true)
            .appendingPathComponent(volume.pulse.isEmpty ? "unknown-pulse" : volume.pulse, isDirectory: true)
            .appendingPathComponent(volume.filename.isEmpty ? "\(item.id)-\(volume.time).h5" : volume.filename)
    }

    func existingSourceURL(for item: CatalogItem, pulse: String, time: String) -> URL? {
        let url: URL
        if item.sourceType == "raw_volume_day", let volume = item.rawVolume(for: pulse, time: time) {
            url = localVolumeURL(for: item, volume: volume)
        } else {
            url = localAggregateURL(for: item)
        }
        return fileManager.fileExists(atPath: url.path) ? url : nil
    }

    func status() -> CacheStatus {
        snapshot().status
    }

    func snapshot() -> RadarCacheSnapshot {
        guard let enumerator = fileManager.enumerator(at: rootDirectory, includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey]) else {
            return RadarCacheSnapshot()
        }
        var count = 0
        var bytes: Int64 = 0
        var filePaths = Set<String>()
        for case let file as URL in enumerator {
            let resourceValues = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard resourceValues?.isRegularFile == true else { continue }
            count += 1
            bytes += Int64(resourceValues?.fileSize ?? 0)
            filePaths.insert(file.path)
        }
        return RadarCacheSnapshot(
            status: CacheStatus(fileCount: count, byteCount: bytes),
            filePaths: filePaths
        )
    }

    func clear() throws -> CacheStatus {
        if fileManager.fileExists(atPath: rootDirectory.path) {
            try fileManager.removeItem(at: rootDirectory)
        }
        return CacheStatus()
    }

    func prune(
        maxAge: TimeInterval = AppConfiguration.cacheTTLSeconds,
        maxBytes: Int64 = AppConfiguration.maxCacheBytes,
        preserving preservedURL: URL? = nil
    ) throws -> CachePruneResult {
        guard let enumerator = fileManager.enumerator(
            at: rootDirectory,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]
        ) else { return CachePruneResult() }

        var files = [(url: URL, size: Int64, modified: Date)]()
        for case let file as URL in enumerator {
            let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey])
            guard values?.isRegularFile == true else { continue }
            let size = Int64(values?.fileSize ?? 0)
            let modified = values?.contentModificationDate ?? .distantPast
            files.append((file, size, modified))
        }

        let preservedPath = preservedURL?.standardizedFileURL.path
        var result = CachePruneResult()
        let now = Date()
        for file in files where maxAge >= 0 && now.timeIntervalSince(file.modified) > maxAge && file.url.standardizedFileURL.path != preservedPath {
            if fileManager.fileExists(atPath: file.url.path) {
                try? fileManager.removeItem(at: file.url)
                if !fileManager.fileExists(atPath: file.url.path) {
                    result.removedFileCount += 1
                    result.removedByteCount += file.size
                }
            }
        }

        files = files.filter { fileManager.fileExists(atPath: $0.url.path) }
        var totalBytes = files.reduce(Int64(0)) { $0 + $1.size }
        for file in files.sorted(by: { $0.modified < $1.modified }) where maxBytes >= 0 && totalBytes > maxBytes && file.url.standardizedFileURL.path != preservedPath {
            if fileManager.fileExists(atPath: file.url.path) {
                try? fileManager.removeItem(at: file.url)
                if !fileManager.fileExists(atPath: file.url.path) {
                    totalBytes -= file.size
                    result.removedFileCount += 1
                    result.removedByteCount += file.size
                }
            }
        }
        return result
    }

    func downloadSelectedSource(for item: CatalogItem, pulse: String, time: String, publicBaseURL: URL = AppConfiguration.publicBaseURL) async throws -> URL {
        if item.sourceType == "raw_volume_day", let volume = item.rawVolume(for: pulse, time: time) {
            return try await downloadVolume(volume, for: item, publicBaseURL: publicBaseURL)
        }
        return try await downloadAggregate(for: item, publicBaseURL: publicBaseURL)
    }

    private func downloadAggregate(for item: CatalogItem, publicBaseURL: URL) async throws -> URL {
        let destination = localAggregateURL(for: item)
        _ = try prune(preserving: destination)
        guard let remoteURL = item.aggregateURL(publicBaseURL: publicBaseURL) else {
            throw RadarAppError.noAggregateURL(item.title)
        }

        return try await download(remoteURL: remoteURL, destination: destination, expectedSize: item.fileSize)
    }

    private func downloadVolume(_ volume: RawVolumeRecord, for item: CatalogItem, publicBaseURL: URL) async throws -> URL {
        let destination = localVolumeURL(for: item, volume: volume)
        _ = try prune(preserving: destination)
        guard let remoteURL = volume.downloadURL(publicBaseURL: publicBaseURL) else {
            throw RadarAppError.noAggregateURL("\(item.title) \(volume.pulse) \(volume.time)")
        }

        return try await download(remoteURL: remoteURL, destination: destination, expectedSize: volume.fileSize)
    }

    private func download(remoteURL: URL, destination: URL, expectedSize: Int64) async throws -> URL {
        if fileManager.fileExists(atPath: destination.path) {
            let cachedSize = Int64((try destination.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? -1)
            if expectedSize <= 0 || cachedSize == expectedSize {
                return destination
            }
            try fileManager.removeItem(at: destination)
        }

        try fileManager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        let (temporaryURL, response) = try await URLSession.shared.download(from: remoteURL)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        if expectedSize > 0 {
            let downloadedSize = Int64((try temporaryURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            if downloadedSize != expectedSize {
                throw RadarAppError.downloadSizeMismatch(remoteURL.lastPathComponent, expectedSize, downloadedSize)
            }
        }
        try? fileManager.removeItem(at: destination)
        try fileManager.moveItem(at: temporaryURL, to: destination)
        _ = try prune(preserving: destination)
        return destination
    }
}
