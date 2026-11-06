import CoreLocation
import Foundation
import MapKit
import UIKit

enum MapUnderlayStyle: String, CaseIterable, Identifiable, Hashable {
    case muted
    case standard
    case satellite

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .muted:
            return "Muted"
        case .standard:
            return "Standard"
        case .satellite:
            return "Satellite"
        }
    }

    var mapType: MKMapType {
        switch self {
        case .muted, .standard:
            return .standard
        case .satellite:
            return .hybrid
        }
    }
}

struct MapOverlaySettings: Hashable {
    var isEnabled = false
    var style: MapUnderlayStyle = .muted
    var opacity = 0.38
}

struct RadarMapSnapshotKey: Hashable {
    var latitude: Double
    var longitude: Double
    var maxRangeM: Double
    var style: MapUnderlayStyle
}

enum MapSnapshotError: LocalizedError {
    case noFrame
    case noLocation

    var errorDescription: String? {
        switch self {
        case .noFrame:
            return "No rendered PPI is available for a map underlay."
        case .noLocation:
            return "No radar location is available for this frame."
        }
    }
}

struct RadarMapSnapshotter {
    static func snapshot(
        for frame: PPIFrame,
        settings: MapOverlaySettings,
        size: CGSize = CGSize(width: 900, height: 900)
    ) async throws -> UIImage {
        guard hasUsableLocation(frame.metadata) else {
            throw MapSnapshotError.noLocation
        }

        let coordinate = CLLocationCoordinate2D(latitude: frame.metadata.latitude, longitude: frame.metadata.longitude)
        let radiusM = max(frame.metadata.maxRangeM, 25_000)
        let latDelta = max(0.08, (radiusM * 2.2) / 111_000)
        let lonScale = max(cos(coordinate.latitude * Double.pi / 180), 0.18)
        let lonDelta = max(0.08, latDelta / lonScale)
        let screenScale = await MainActor.run { UIScreen.main.scale }

        let options = MKMapSnapshotter.Options()
        options.region = MKCoordinateRegion(
            center: coordinate,
            span: MKCoordinateSpan(latitudeDelta: latDelta, longitudeDelta: lonDelta)
        )
        options.size = size
        options.scale = screenScale
        options.mapType = settings.style.mapType
        options.showsBuildings = false
        if settings.style == .muted {
            options.pointOfInterestFilter = .excludingAll
        }

        return try await withCheckedThrowingContinuation { continuation in
            MKMapSnapshotter(options: options).start { snapshot, error in
                if let snapshot {
                    continuation.resume(returning: snapshot.image)
                } else {
                    continuation.resume(throwing: error ?? MapSnapshotError.noLocation)
                }
            }
        }
    }

    static func hasUsableLocation(_ metadata: RadarGridMetadata) -> Bool {
        metadata.latitude.isFinite &&
            metadata.longitude.isFinite &&
            (-90...90).contains(metadata.latitude) &&
            (-180...180).contains(metadata.longitude) &&
            abs(metadata.latitude) + abs(metadata.longitude) > 0.001
    }
}
