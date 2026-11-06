import Foundation

struct CacheStatus: Hashable {
    var fileCount: Int = 0
    var byteCount: Int64 = 0

    var displayText: String {
        guard fileCount > 0 else { return "Raw cache empty" }
        return "\(fileCount) file\(fileCount == 1 ? "" : "s"), \(Self.byteString(byteCount))"
    }

    static func byteString(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useMB, .useGB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
}

struct RadarCacheSnapshot: Sendable {
    var status = CacheStatus()
    var filePaths = Set<String>()
}

struct CachePruneResult: Hashable {
    var removedFileCount: Int = 0
    var removedByteCount: Int64 = 0
}

struct RenderPerformance: Hashable {
    var usedCachedSource: Bool
    var sourceSeconds: Double
    var hdf5ReadSeconds: Double
    var renderSeconds: Double
    var totalSeconds: Double

    var displayText: String {
        let source = usedCachedSource ? "cache" : "download"
        return String(
            format: "%@ %.1fs · read %.1fs · render %.1fs · total %.1fs",
            source,
            sourceSeconds,
            hdf5ReadSeconds,
            renderSeconds,
            totalSeconds
        )
    }
}

extension RadarGridMetadata {
    var statusDisplayLine: String {
        "Rendered · \(displayRadarName) · \(formattedDateText) · \(pulse) \(time) · \(quantity) · \(elevationText)"
    }

    var statusPrimaryLine: String {
        "\(displayRadarName) · \(formattedDateText)"
    }

    var statusSecondaryLine: String {
        "\(pulse) \(time) · \(quantity) · \(elevationText)"
    }

    var radarDisplayLine: String {
        "\(displayRadarName) \(formattedDateText) \(quantity)"
    }

    var sweepDisplayLine: String {
        "\(pulse) \(time) \(elevationText)"
    }

    private var displayRadarName: String {
        radar
            .split(separator: "-")
            .map { part in part.prefix(1).uppercased() + part.dropFirst() }
            .joined(separator: " ")
    }

    private var formattedDateText: String {
        guard date.count == 8 else { return date }
        let year = date.prefix(4)
        let month = date.dropFirst(4).prefix(2)
        let day = date.suffix(2)
        return "\(year)-\(month)-\(day)"
    }

    private var elevationText: String {
        elevationDeg.map { String(format: "%.2f°", $0) } ?? "elevation n/a"
    }
}
