import Foundation
import UIKit

enum VideoExportError: LocalizedError, Equatable {
    case notEnoughFrames
    case noFrames
    case cancelled
    case backgroundTimeExpired

    var errorDescription: String? {
        switch self {
        case .notEnoughFrames:
            return "At least two scan times are needed to make a video."
        case .noFrames:
            return "No scans could be rendered for the video."
        case .cancelled:
            return "Video export was cancelled."
        case .backgroundTimeExpired:
            return "Export stopped because iOS background time expired. Keep UK WSR open for longer videos."
        }
    }
}

struct VideoFrameExportSummary: Hashable {
    var requestedFrames: Int
    var renderedFrames: Int
    var skippedFrames: Int
    var stoppedEarly: Bool
    var metrics = VideoExportMetrics()
}

enum VideoExportMode: String, CaseIterable, Identifiable, Hashable {
    case fast
    case preview
    case resumeSafe

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .fast:
            return "Fast"
        case .preview:
            return "Preview"
        case .resumeSafe:
            return "Resume"
        }
    }

    var statusName: String {
        switch self {
        case .fast:
            return "Fast"
        case .preview:
            return "Preview"
        case .resumeSafe:
            return "Resume-safe"
        }
    }

    var quality: VideoExportQuality {
        switch self {
        case .fast, .resumeSafe:
            return .full
        case .preview:
            return .preview
        }
    }
}

enum VideoExportQuality: String, Hashable {
    case full
    case preview

    var size: CGSize {
        switch self {
        case .full:
            return CGSize(width: 900, height: 900)
        case .preview:
            return CGSize(width: 600, height: 600)
        }
    }

    var framesPerSecond: Int32 { 8 }
}

struct VideoExportMetrics: Hashable {
    var downloadSeconds = 0.0
    var hdf5ReadSeconds = 0.0
    var radarRenderSeconds = 0.0
    var imageDrawSeconds = 0.0
    var encodeSeconds = 0.0
    var totalSeconds = 0.0

    var summaryText: String {
        String(
            format: "Export speed: %.1fs total · dl %.1fs · read %.1fs · render %.1fs · draw %.1fs · encode %.1fs",
            totalSeconds,
            downloadSeconds,
            hdf5ReadSeconds,
            radarRenderSeconds,
            imageDrawSeconds,
            encodeSeconds
        )
    }
}

struct VideoFrameWriteTiming: Hashable {
    var drawSeconds = 0.0
    var encodeSeconds = 0.0
}

struct VideoExportFrameRequest: Hashable {
    var index: Int
    var time: String
    var selection: FieldSelection
}

struct VideoExportPlan: Hashable {
    var mode: VideoExportMode
    var quality: VideoExportQuality
    var item: CatalogItem
    var pulse: String
    var quantity: String
    var dataset: String
    var filters: RadarFilterSet
    var requestedTimes: [String]
    var frameRequests: [VideoExportFrameRequest]

    var skippedFrameCount: Int {
        max(0, requestedTimes.count - frameRequests.count)
    }
}

struct VideoFrameRenderResult {
    var frame: PPIFrame
    var hdf5ReadSeconds: Double
    var radarRenderSeconds: Double
    var decodedCacheHit = false
    var renderedCacheHit = false
}
