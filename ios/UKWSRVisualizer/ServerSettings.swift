import CoreLocation
import Foundation
import MapKit
import UIKit

enum AppConfiguration {
    static let publicBaseURL = URL(string: "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public")!
    static let publicCatalogURL = URL(string: "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json")!
    static let maxCacheBytes: Int64 = 8 * 1024 * 1024 * 1024
    static let cacheTTLSeconds: TimeInterval = 7 * 24 * 60 * 60
    static let renderDebounceNanoseconds: UInt64 = 180_000_000
}

enum AppRuntime {
    static var isUITesting: Bool {
        ProcessInfo.processInfo.arguments.contains("-UKWSRUITesting")
    }
}

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

struct CachePruneResult: Hashable {
    var removedFileCount: Int = 0
    var removedByteCount: Int64 = 0
}

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
}

private struct RadarMapSnapshotter {
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

private actor RadarRenderWorker {
    private let reader: RadarVolumeReader
    private let renderer = RadarRenderer()
    private var loadedBackgroundModels: [String: BackgroundModel] = [:]

    init(reader: RadarVolumeReader) {
        self.reader = reader
    }

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        try reader.inspectFields(from: fileURL, item: item, pulse: pulse, time: time)
    }

    func renderFrame(
        from fileURL: URL,
        item: CatalogItem,
        selection: FieldSelection,
        filters: RadarFilterSet,
        backgroundModels: [BackgroundModelDescriptor]
    ) throws -> PPIFrame {
        let field = try reader.readPolarField(from: fileURL, item: item, selection: selection)
        let backgroundModel = matchingBackgroundModel(for: field, in: backgroundModels)
        return renderer.render(field: field, filters: filters, backgroundModel: backgroundModel)
    }

    func renderFrameWithTimings(
        from fileURL: URL,
        item: CatalogItem,
        selection: FieldSelection,
        filters: RadarFilterSet,
        backgroundModels: [BackgroundModelDescriptor]
    ) throws -> VideoFrameRenderResult {
        let readStart = Date()
        let field = try reader.readPolarField(from: fileURL, item: item, selection: selection)
        let readSeconds = Date().timeIntervalSince(readStart)
        let renderStart = Date()
        let backgroundModel = matchingBackgroundModel(for: field, in: backgroundModels)
        let frame = renderer.render(field: field, filters: filters, backgroundModel: backgroundModel)
        let renderSeconds = Date().timeIntervalSince(renderStart)
        return VideoFrameRenderResult(
            frame: frame,
            hdf5ReadSeconds: readSeconds,
            radarRenderSeconds: renderSeconds
        )
    }

    private func matchingBackgroundModel(for field: PolarField, in models: [BackgroundModelDescriptor]) -> BackgroundModel? {
        let gateQuantity = field.gateQuantity ?? (isReflectivityQuantity(field.metadata.quantity) ? field.metadata.quantity : nil)
        guard let descriptor = models.first(where: { $0.matches(metadata: field.metadata, gateQuantity: gateQuantity) }) else {
            return nil
        }
        if let cached = loadedBackgroundModels[descriptor.modelKey] {
            return cached
        }
        guard let model = try? BackgroundModel.load(from: descriptor.url) else {
            return nil
        }
        loadedBackgroundModels[descriptor.modelKey] = model
        return model
    }
}

struct CatalogSearchCriteria: Hashable {
    var radar = ""
    var year = ""
    var pulse = ""
    var quantity = ""
    var startDate = ""
    var endDate = ""
    var text = ""
    var renderableOnly = false
    var cachedOnly = false
    var sortMode: CatalogSortMode = .newestFirst
}

enum CatalogSortMode: String, CaseIterable, Hashable, Codable {
    case newestFirst
    case radarThenNewest
    case cachedFirst

    var displayName: String {
        switch self {
        case .newestFirst:
            return "Newest first"
        case .radarThenNewest:
            return "Radar, newest"
        case .cachedFirst:
            return "Cached first"
        }
    }
}

struct SourceDiagnosticRow: Identifiable, Hashable {
    var label: String
    var value: String

    var id: String { label }
}

struct LaunchDefaultSelection: Hashable {
    var itemID: String
    var statusText: String
    var preferLatestTime = true
}

struct RecentCatalogSelection: Codable, Hashable, Identifiable {
    var itemID: String
    var radar: String
    var radarDisplayName: String
    var date: String
    var pulse: String
    var time: String
    var quantity: String
    var dataset: String
    var selectedAt: Date

    var id: String { itemID }

    var title: String {
        "\(radarDisplayName) \(CatalogItem.formattedDate(date))"
    }

    var detailText: String {
        [pulse, time, quantity]
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }
}

protocol RecentSelectionStoring {
    func loadRecentSelections() -> [RecentCatalogSelection]
    func saveRecentSelections(_ selections: [RecentCatalogSelection])
}

struct UserDefaultsRecentSelectionStore: RecentSelectionStoring {
    private let defaults: UserDefaults
    private let key: String

    init(
        defaults: UserDefaults = .standard,
        key: String = "UKWSRRecentCatalogSelections"
    ) {
        self.defaults = defaults
        self.key = key
    }

    func loadRecentSelections() -> [RecentCatalogSelection] {
        guard let data = defaults.data(forKey: key),
              let selections = try? JSONDecoder().decode([RecentCatalogSelection].self, from: data) else {
            return []
        }
        return selections.sorted { $0.selectedAt > $1.selectedAt }
    }

    func saveRecentSelections(_ selections: [RecentCatalogSelection]) {
        guard let data = try? JSONEncoder().encode(selections) else { return }
        defaults.set(data, forKey: key)
    }
}

@MainActor
protocol DeviceLocationProviding {
    func requestCurrentLocation(timeout: TimeInterval) async -> CLLocation?
}

@MainActor
final class DeviceLocationProvider: NSObject, DeviceLocationProviding, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?
    private var timeoutTask: Task<Void, Never>?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
    }

    func requestCurrentLocation(timeout: TimeInterval = 4) async -> CLLocation? {
        guard CLLocationManager.locationServicesEnabled() else { return nil }
        if let recent = manager.location, abs(recent.timestamp.timeIntervalSinceNow) < 15 * 60 {
            return recent
        }

        return await withCheckedContinuation { continuation in
            finishExistingRequest(with: nil)
            self.continuation = continuation
            timeoutTask = Task { [weak self] in
                let nanoseconds = UInt64(max(timeout, 0.5) * 1_000_000_000)
                try? await Task.sleep(nanoseconds: nanoseconds)
                await MainActor.run {
                    guard let self else { return }
                    self.finish(with: self.manager.location)
                }
            }

            switch manager.authorizationStatus {
            case .notDetermined:
                manager.requestWhenInUseAuthorization()
            case .authorizedAlways, .authorizedWhenInUse:
                manager.requestLocation()
            case .denied, .restricted:
                finish(with: manager.location)
            @unknown default:
                finish(with: manager.location)
            }
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            finish(with: manager.location)
        case .notDetermined:
            break
        @unknown default:
            finish(with: manager.location)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        finish(with: locations.sorted { $0.horizontalAccuracy < $1.horizontalAccuracy }.first ?? manager.location)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(with: manager.location)
    }

    private func finishExistingRequest(with location: CLLocation?) {
        guard continuation != nil else { return }
        finish(with: location)
    }

    private func finish(with location: CLLocation?) {
        timeoutTask?.cancel()
        timeoutTask = nil
        let currentContinuation = continuation
        continuation = nil
        currentContinuation?.resume(returning: location)
    }
}

@MainActor
struct StaticDeviceLocationProvider: DeviceLocationProviding {
    var location: CLLocation?

    func requestCurrentLocation(timeout: TimeInterval) async -> CLLocation? {
        location
    }
}

typealias CatalogDataLoader = (URL) async throws -> Data

struct CatalogService {
    var catalogURL: URL
    var publicBaseURL: URL
    var dataLoader: CatalogDataLoader

    init(
        catalogURL: URL = AppConfiguration.publicCatalogURL,
        publicBaseURL: URL = AppConfiguration.publicBaseURL,
        dataLoader: @escaping CatalogDataLoader = CatalogService.liveData(from:)
    ) {
        self.catalogURL = catalogURL
        self.publicBaseURL = publicBaseURL
        self.dataLoader = dataLoader
    }

    func fetchCatalog() async throws -> [CatalogItem] {
        let data = try await fetchData(from: catalogURL)
        let decoder = JSONDecoder()
        let rootDecodeError: Error?
        do {
            let pvolRoot = try decoder.decode(InterimPVOLRootCatalog.self, from: data)
            if !pvolRoot.radars.isEmpty {
                return try await fetchLatestPVOLDays(from: pvolRoot, publicBaseURL: publicBaseURL)
            }
            rootDecodeError = nil
        } catch {
            rootDecodeError = error
        }
        do {
            return try decoder.decode(CatalogEnvelope.self, from: data).items.sorted {
                ($0.radar, $0.date) < ($1.radar, $1.date)
            }
        } catch {
            let detail = rootDecodeError.map { "PVOL root: \($0.localizedDescription); legacy envelope: \(error.localizedDescription)" } ?? error.localizedDescription
            throw RadarAppError.catalogDecodeFailed(detail)
        }
    }

    func fetchPVOLRootCatalog() async throws -> InterimPVOLRootCatalog {
        try await fetchInterimPVOLRoot()
    }

    func fetchCoverageDays(forRadar radar: String, years: [String], publicBaseURL: URL? = nil) async throws -> [CatalogItem] {
        let root = try await fetchInterimPVOLRoot()
        guard let radarRecord = root.radars.first(where: { $0.radar == radar }) else { return [] }
        let requestedYears = Set(years)
        let coverageKeys = radarRecord.coverageKeys.filter { key in
            requestedYears.isEmpty || requestedYears.contains(Self.year(fromCoverageKey: key))
        }

        var items: [CatalogItem] = []
        let baseURL = publicBaseURL ?? self.publicBaseURL
        for key in coverageKeys {
            let coverage = try await fetchPVOLCoverage(key: key, publicBaseURL: baseURL)
            items.append(contentsOf: coverage.days.map { day in
                CatalogItem(interimPVOLDay: day, radar: radarRecord, root: root)
            })
        }
        return items.sorted {
            ($0.radar, $0.date, $0.rawVolumeCatalogKey) < ($1.radar, $1.date, $1.rawVolumeCatalogKey)
        }
    }

    func fetchRawVolumeCatalog(for item: CatalogItem, publicBaseURL: URL? = nil) async throws -> [CatalogItem] {
        let baseURL = publicBaseURL ?? self.publicBaseURL
        guard let url = item.rawVolumeCatalogDownloadURL(publicBaseURL: baseURL) else {
            return []
        }
        let data = try await fetchData(from: url)
        let decoder = JSONDecoder()
        if let dayCatalog = try? decoder.decode(InterimPVOLDayCatalog.self, from: data), !dayCatalog.files.isEmpty {
            return dayCatalog.files.map { file in
                CatalogItem(interimPVOLFile: file, day: dayCatalog)
            }
            .sorted {
                ($0.pulses.first ?? "", $0.times.first ?? "", $0.objectKey) <
                    ($1.pulses.first ?? "", $1.times.first ?? "", $1.objectKey)
            }
        }
        return try decoder.decode(CatalogEnvelope.self, from: data).items.sorted {
            ($0.pulses.first ?? "", $0.times.first ?? "", $0.objectKey) <
                ($1.pulses.first ?? "", $1.times.first ?? "", $1.objectKey)
        }
    }

    private func fetchInterimPVOLRoot() async throws -> InterimPVOLRootCatalog {
        let data = try await fetchData(from: catalogURL)
        return try JSONDecoder().decode(InterimPVOLRootCatalog.self, from: data)
    }

    private func fetchLatestPVOLDays(from root: InterimPVOLRootCatalog, publicBaseURL: URL = AppConfiguration.publicBaseURL) async throws -> [CatalogItem] {
        var items: [CatalogItem] = []
        for radar in root.radars {
            for coverageKey in radar.coverageKeys.reversed() {
                guard let coverage = try? await fetchPVOLCoverage(key: coverageKey, publicBaseURL: publicBaseURL) else {
                    continue
                }
                if let latestDay = coverage.days.max(by: { $0.date < $1.date }) {
                    items.append(CatalogItem(interimPVOLDay: latestDay, radar: radar, root: root))
                    break
                }
            }
        }
        return items.sorted {
            ($0.radar, $0.date) < ($1.radar, $1.date)
        }
    }

    private func fetchPVOLCoverage(key: String, publicBaseURL: URL) async throws -> InterimPVOLCoverage {
        let url = Self.objectStoreURL(base: publicBaseURL, key: key)
        let data = try await fetchData(from: url)
        return try JSONDecoder().decode(InterimPVOLCoverage.self, from: data)
    }

    private func fetchData(from url: URL) async throws -> Data {
        try await dataLoader(url)
    }

    private static func liveData(from url: URL) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private static func year(fromCoverageKey key: String) -> String {
        key.split(separator: "/").dropLast().last.map(String.init) ?? ""
    }

    private static func objectStoreURL(base: URL, key: String) -> URL {
        URL(string: base.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + key.trimmingCharacters(in: CharacterSet(charactersIn: "/")))!
    }
}

extension CatalogService {
    static var uiTestFixtures: CatalogService {
        CatalogService(
            catalogURL: UITestCatalogFixtures.rootURL,
            publicBaseURL: UITestCatalogFixtures.baseURL
        ) { url in
            try UITestCatalogFixtures.data(for: url)
        }
    }
}

private enum UITestCatalogFixtures {
    static let rootURL = URL(string: "https://ui-test.invalid/ukmo-nimrod/catalog/pvol/catalog.json")!
    static let baseURL = URL(string: "https://ui-test.invalid")!

    static func data(for url: URL) throws -> Data {
        guard let body = responses[url.absoluteString] else {
            throw URLError(.fileDoesNotExist)
        }
        return Data(body.utf8)
    }

    private static let responses = [
        rootURL.absoluteString: rootJSON,
        "https://ui-test.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json": castorCoverageJSON,
        "https://ui-test.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json": cheniesCoverageJSON,
        "https://ui-test.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/06/29/catalog.json": castorDayCatalogJSON,
        "https://ui-test.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/06/28/catalog.json": cheniesDayCatalogJSON,
    ]

    private static let rootJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T18:00:00Z",
      "interim": false,
      "upload_complete": true,
      "file_count": 4,
      "size_bytes": 4096,
      "radars": [
        {
          "radar": "castor-bay",
          "radar_num": "07",
          "years": ["2026"],
          "coverage_keys": ["ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json"],
          "first_date": "20260629",
          "last_date": "20260629",
          "date_count": 1,
          "file_count": 2,
          "size_bytes": 2048,
          "spatial": {
            "latitude": 54.50194444444445,
            "longitude": -6.342777777777777,
            "height_m": 41.0,
            "source": "ui-test"
          }
        },
        {
          "radar": "chenies",
          "radar_num": "05",
          "years": ["2026"],
          "coverage_keys": ["ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json"],
          "first_date": "20260628",
          "last_date": "20260628",
          "date_count": 1,
          "file_count": 2,
          "size_bytes": 2048,
          "spatial": {
            "latitude": 51.68944444444444,
            "longitude": -0.5302777777777778,
            "height_m": 153.0,
            "source": "ui-test"
          }
        }
      ]
    }
    """

    private static let castorCoverageJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T18:00:00Z",
      "interim": false,
      "upload_complete": true,
      "radar": "castor-bay",
      "year": "2026",
      "days": [
        {
          "date": "20260629",
          "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/29/catalog.json",
          "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/29",
          "file_count": 2,
          "size_bytes": 2048,
          "pulse_counts": {"lp": 2}
        }
      ]
    }
    """

    private static let cheniesCoverageJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T18:00:00Z",
      "interim": false,
      "upload_complete": true,
      "radar": "chenies",
      "year": "2026",
      "days": [
        {
          "date": "20260628",
          "catalog_key": "ukmo-nimrod/catalog/pvol/chenies/2026/06/28/catalog.json",
          "pvol_prefix": "ukmo-nimrod/pvol/chenies/2026/06/28",
          "file_count": 2,
          "size_bytes": 2048,
          "pulse_counts": {"lp": 2}
        }
      ]
    }
    """

    private static let castorDayCatalogJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T18:00:00Z",
      "interim": false,
      "upload_complete": true,
      "radar": "castor-bay",
      "radar_num": "07",
      "date": "20260629",
      "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/29/catalog.json",
      "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/29",
      "file_count": 2,
      "size_bytes": 2048,
      "pulses": ["lp"],
      "pulse_counts": {"lp": 2},
      "times_by_pulse": {"lp": ["1200", "1205"]},
      "files": [
        {
          "pulse": "lp",
          "time": "1200",
          "filename": "castor-lp-1200.h5",
          "size_bytes": 1024,
          "modified_time": 1782756000,
          "object_key": "ukmo-nimrod/pvol/castor-bay/2026/06/29/lp/castor-lp-1200.h5",
          "object_url": "https://ui-test.invalid/ukmo-nimrod/pvol/castor-bay/2026/06/29/lp/castor-lp-1200.h5"
        },
        {
          "pulse": "lp",
          "time": "1205",
          "filename": "castor-lp-1205.h5",
          "size_bytes": 1024,
          "modified_time": 1782756300,
          "object_key": "ukmo-nimrod/pvol/castor-bay/2026/06/29/lp/castor-lp-1205.h5",
          "object_url": "https://ui-test.invalid/ukmo-nimrod/pvol/castor-bay/2026/06/29/lp/castor-lp-1205.h5"
        }
      ]
    }
    """

    private static let cheniesDayCatalogJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T18:00:00Z",
      "interim": false,
      "upload_complete": true,
      "radar": "chenies",
      "radar_num": "05",
      "date": "20260628",
      "catalog_key": "ukmo-nimrod/catalog/pvol/chenies/2026/06/28/catalog.json",
      "pvol_prefix": "ukmo-nimrod/pvol/chenies/2026/06/28",
      "file_count": 2,
      "size_bytes": 2048,
      "pulses": ["lp"],
      "pulse_counts": {"lp": 2},
      "times_by_pulse": {"lp": ["1210", "1215"]},
      "files": [
        {
          "pulse": "lp",
          "time": "1210",
          "filename": "chenies-lp-1210.h5",
          "size_bytes": 1024,
          "modified_time": 1782756600,
          "object_key": "ukmo-nimrod/pvol/chenies/2026/06/28/lp/chenies-lp-1210.h5",
          "object_url": "https://ui-test.invalid/ukmo-nimrod/pvol/chenies/2026/06/28/lp/chenies-lp-1210.h5"
        },
        {
          "pulse": "lp",
          "time": "1215",
          "filename": "chenies-lp-1215.h5",
          "size_bytes": 1024,
          "modified_time": 1782756900,
          "object_key": "ukmo-nimrod/pvol/chenies/2026/06/28/lp/chenies-lp-1215.h5",
          "object_url": "https://ui-test.invalid/ukmo-nimrod/pvol/chenies/2026/06/28/lp/chenies-lp-1215.h5"
        }
      ]
    }
    """
}

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
        guard let enumerator = fileManager.enumerator(at: rootDirectory, includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey]) else {
            return CacheStatus()
        }
        var count = 0
        var bytes: Int64 = 0
        for case let file as URL in enumerator {
            let resourceValues = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard resourceValues?.isRegularFile == true else { continue }
            count += 1
            bytes += Int64(resourceValues?.fileSize ?? 0)
        }
        return CacheStatus(fileCount: count, byteCount: bytes)
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

@MainActor
private struct DatasetSelectionPreference: Equatable {
    var dataset: String
    var elevationDeg: Double?
    var nominalHeightM: Double?
}

@MainActor
final class VisualizerViewModel: ObservableObject {
    @Published var catalog: [CatalogItem] = []
    @Published var selectedItemID: String?
    @Published var selectedPulse = ""
    @Published var selectedTime = ""
    @Published var selectedQuantity = ""
    @Published var selectedDataset = ""
    @Published var filters = RadarFilterSet()
    @Published var showDataID = false
    @Published var showDetailedIdentifyReadout = true
    @Published var frame: PPIFrame?
    @Published var identifyResult: IdentifyResult?
    @Published var isLoadingCatalog = false
    @Published var hasCompletedInitialLoad = false
    @Published var isDownloading = false
    @Published var isRendering = false
    @Published var statusMessage = "Load the public catalog to begin."
    @Published var warningMessage: String?
    @Published var cacheStatus = CacheStatus()
    @Published var catalogSearch = CatalogSearchCriteria()
    @Published var isLoadingCoverage = false
    @Published private var catalogRadarAvailability: [String: InterimPVOLRadar] = [:]
    @Published var recentSelections: [RecentCatalogSelection] = []
    @Published var mapSettings = MapOverlaySettings()
    @Published var mapSnapshotImage: UIImage?
    @Published var isLoadingMapSnapshot = false
    @Published var mapStatusMessage = "Map off"
    @Published var isExportingVideo = false
    @Published var videoExportProgress = ""

    private let catalogService: CatalogService
    private let cache: RadarCache
    private let renderWorker: RadarRenderWorker
    private let locationProvider: DeviceLocationProviding
    private let recentSelectionStore: RecentSelectionStoring
    private let autoRenderEnabled: Bool
    private var renderRequestID = 0
    private var renderDebounceTask: Task<Void, Never>?
    private var hasAppliedLaunchDefaultSelection = false
    private var loadedCoverageYears = Set<String>()
    private var pendingDatasetPreference: DatasetSelectionPreference?
    private var backgroundModels: [BackgroundModelDescriptor] = []

    init(
        catalogService: CatalogService? = nil,
        cache: RadarCache? = nil,
        hdf5Reader: RadarVolumeReader? = nil,
        locationProvider: DeviceLocationProviding? = nil,
        recentSelectionStore: RecentSelectionStoring = UserDefaultsRecentSelectionStore(),
        autoRenderEnabled: Bool? = nil
    ) {
        let isUITesting = AppRuntime.isUITesting
        let resolvedCache = cache ?? .live
        self.catalogService = catalogService ?? (isUITesting ? .uiTestFixtures : CatalogService())
        self.cache = resolvedCache
        self.renderWorker = RadarRenderWorker(reader: hdf5Reader ?? NativeHDF5VolumeReader())
        self.recentSelectionStore = recentSelectionStore
        if let locationProvider {
            self.locationProvider = locationProvider
        } else if isUITesting {
            self.locationProvider = StaticDeviceLocationProvider(location: CLLocation(latitude: 54.5, longitude: -6.34))
        } else {
            self.locationProvider = DeviceLocationProvider()
        }
        self.autoRenderEnabled = autoRenderEnabled ?? !isUITesting
        loadBackgroundModelIfAvailable()
        self.cacheStatus = resolvedCache.status()
        self.recentSelections = recentSelectionStore.loadRecentSelections()
    }

    private func loadBackgroundModelIfAvailable() {
        let fileManager = FileManager.default
        var candidates = [URL]()
        if let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first {
            candidates.append(documents.appendingPathComponent("background-model.json"))
            appendBackgroundModelURLs(from: documents.appendingPathComponent("BackgroundModels"), to: &candidates)
        }
        if let bundled = Bundle.main.url(forResource: "background-model", withExtension: "json") {
            candidates.append(bundled)
        }
        if let bundled = Bundle.main.urls(forResourcesWithExtension: "json", subdirectory: "BackgroundModels") {
            candidates.append(contentsOf: bundled)
        }

        var seen = Set<String>()
        for url in candidates where fileManager.fileExists(atPath: url.path) {
            if let descriptor = try? BackgroundModelDescriptor.load(from: url) {
                let key = descriptor.modelKey
                if seen.insert(key).inserted {
                    backgroundModels.append(descriptor)
                }
            }
        }
        if !backgroundModels.isEmpty {
            filters.backgroundModelEnabled = true
        }
    }

    private func appendBackgroundModelURLs(from directory: URL, to candidates: inout [URL]) {
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) else {
            return
        }
        candidates.append(contentsOf: urls.filter { $0.pathExtension.lowercased() == "json" })
    }

    var selectedItem: CatalogItem? {
        guard let selectedItemID else { return nil }
        return catalog.first { $0.id == selectedItemID }
    }

    var shouldShowLaunchLoadingScreen: Bool {
        !hasCompletedInitialLoad && (isLoadingCatalog || catalog.isEmpty)
    }

    var catalogRadarOptions: [String] {
        let radars = Set(catalog.map(\.radar).filter { !$0.isEmpty })
            .union(catalogRadarAvailability.keys)
        return Array(radars).sorted {
            radarDisplayName($0) < radarDisplayName($1)
        }
    }

    var catalogYearOptions: [String] {
        if !catalogSearch.radar.isEmpty,
           let rootYears = catalogRadarAvailability[catalogSearch.radar]?.years,
           !rootYears.isEmpty {
            return rootYears.sorted(by: >)
        }

        var years = Set<String>()
        years.formUnion(catalogRadarAvailability.values.flatMap(\.years))
        years.formUnion(catalog.compactMap { Self.yearString(from: $0.date) })
        return Array(years).sorted(by: >)
    }

    var catalogDateRange: (start: String, end: String)? {
        if !catalogSearch.radar.isEmpty,
           let availability = catalogRadarAvailability[catalogSearch.radar],
           !availability.firstDate.isEmpty,
           !availability.lastDate.isEmpty {
            return (availability.firstDate, availability.lastDate)
        }
        let matchingDates = catalog
            .filter { catalogSearch.radar.isEmpty || $0.radar == catalogSearch.radar }
            .map(\.date)
            .filter { !$0.isEmpty }
            .sorted()
        guard let start = matchingDates.first, let end = matchingDates.last else { return nil }
        return (start, end)
    }

    var catalogPulseOptions: [String] {
        let criteria = catalogSearch
        let matchingItems = catalog.filter { item in
            if !criteria.radar.isEmpty && item.radar != criteria.radar { return false }
            if !criteria.year.isEmpty && Self.yearString(from: item.date) != criteria.year { return false }
            if let start = Self.compactCatalogDate(criteria.startDate), item.date < start { return false }
            if let end = Self.compactCatalogDate(criteria.endDate), item.date > end { return false }
            return true
        }
        let pulses = matchingItems.flatMap { item in
            item.pulses + item.quantityRecords.map(\.pulse) + item.rawVolumes.map(\.pulse)
        }
        return Array(Set(pulses.filter { !$0.isEmpty })).sorted()
    }

    var catalogQuantityOptions: [String] {
        let criteria = catalogSearch
        let matchingItems = catalog.filter { item in
            if !criteria.radar.isEmpty && item.radar != criteria.radar { return false }
            if !criteria.year.isEmpty && Self.yearString(from: item.date) != criteria.year { return false }
            if let start = Self.compactCatalogDate(criteria.startDate), item.date < start { return false }
            if let end = Self.compactCatalogDate(criteria.endDate), item.date > end { return false }
            if !criteria.pulse.isEmpty && !item.matchesPulse(criteria.pulse) { return false }
            return true
        }
        let quantities = matchingItems.flatMap { item in
            item.quantities + item.quantityRecords.map(\.quantity) + item.rawVolumes.flatMap(\.quantities)
        }
        return Array(Set(quantities.filter { !$0.isEmpty })).sorted()
    }

    var filteredCatalogItems: [CatalogItem] {
        let criteria = catalogSearch
        let start = Self.compactCatalogDate(criteria.startDate)
        let end = Self.compactCatalogDate(criteria.endDate)
        let tokens = criteria.text
            .lowercased()
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)

        return catalog.filter { item in
            if !criteria.radar.isEmpty && item.radar != criteria.radar { return false }
            if !criteria.year.isEmpty && Self.yearString(from: item.date) != criteria.year { return false }
            if let start, item.date < start { return false }
            if let end, item.date > end { return false }
            if !criteria.pulse.isEmpty && !item.matchesPulse(criteria.pulse) { return false }
            if !criteria.quantity.isEmpty && !item.matchesQuantity(criteria.quantity) { return false }
            if criteria.renderableOnly && !isPotentiallyRenderable(item) { return false }
            if criteria.cachedOnly && !isCatalogItemCached(item) { return false }
            guard !tokens.isEmpty else { return true }
            let haystack = item.searchText.lowercased()
            return tokens.allSatisfy { haystack.contains($0) }
        }
        .sorted(by: sortCatalogItems)
    }

    var catalogSearchSummary: String {
        let count = filteredCatalogItems.count
        guard !catalog.isEmpty else { return "No catalog" }
        if count == catalog.count {
            return "\(count) item\(count == 1 ? "" : "s")"
        }
        return "\(count) of \(catalog.count) item\(catalog.count == 1 ? "" : "s")"
    }

    var catalogCoverageStatusText: String {
        guard !catalogSearch.radar.isEmpty else {
            return "Select a radar to load full published year coverage lazily."
        }
        let years = yearsForCurrentSearch(radar: catalogSearch.radar)
        guard !years.isEmpty else {
            return "Set a date or use Latest day to choose which published year to load."
        }
        let loadedYears = years.filter { loadedCoverageYears.contains(Self.coverageKey(radar: catalogSearch.radar, year: $0)) }
        if loadedYears.count == years.count {
            return "Loaded published coverage for \(radarDisplayName(catalogSearch.radar)) \(years.joined(separator: ", "))."
        }
        let missingYears = years.filter { !loadedCoverageYears.contains(Self.coverageKey(radar: catalogSearch.radar, year: $0)) }
        return "Coverage for \(radarDisplayName(catalogSearch.radar)) \(missingYears.joined(separator: ", ")) will load on demand."
    }

    func isCatalogItemCached(_ item: CatalogItem) -> Bool {
        if item.sourceType == "raw_volume_day" {
            if item.rawVolumes.contains(where: { volume in
                cache.fileManager.fileExists(atPath: cache.localVolumeURL(for: item, volume: volume).path)
            }) {
                return true
            }
            return cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) != nil
        }
        return cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) != nil
    }

    func isPotentiallyRenderable(_ item: CatalogItem) -> Bool {
        let hasFieldMetadata =
            !item.pulses.isEmpty ||
            !item.quantityRecords.isEmpty ||
            !item.rawVolumes.isEmpty ||
            !item.quantitiesByPulse.isEmpty

        if item.sourceType == "raw_volume_day" {
            return hasDownloadableSource(item) && hasFieldMetadata
        }

        return item.aggregateURL(publicBaseURL: AppConfiguration.publicBaseURL) != nil && hasFieldMetadata
    }

    func catalogRowBadges(for item: CatalogItem) -> [String] {
        var badges: [String] = []
        if isCatalogItemCached(item) {
            badges.append("Cached")
        }
        if isPotentiallyRenderable(item) {
            badges.append("Renderable")
        }
        if item.sourceType == "raw_volume_day", item.rawVolumes.isEmpty, item.rawVolumeCatalogDownloadURL(publicBaseURL: AppConfiguration.publicBaseURL) != nil {
            badges.append("Scan catalog")
        }
        if item.pulses.isEmpty && item.quantityRecords.isEmpty && item.rawVolumes.isEmpty {
            badges.append("No pulses")
        }
        let hasConfirmedVariables = !item.quantities.isEmpty ||
            !item.quantityRecords.isEmpty ||
            item.rawVolumes.contains { !$0.quantities.isEmpty }
        if !hasConfirmedVariables && !hasDownloadableSource(item) {
            badges.append("No variables")
        }
        if !hasDownloadableSource(item) {
            badges.append("No source")
        }
        return badges
    }

    func catalogRowDetailText(for item: CatalogItem) -> String {
        [
            item.radarNum.isEmpty ? nil : "Radar \(item.radarNum)",
            item.validationStatus.isEmpty ? nil : item.validationStatus.capitalized,
            item.sourceType == "raw_volume_day" ? "Raw volume day" : "Aggregate day",
            item.fileSize > 0 ? CacheStatus.byteString(item.fileSize) : nil,
        ]
        .compactMap { $0 }
        .joined(separator: ", ")
    }

    func catalogRowFacetText(for item: CatalogItem) -> String {
        let pulses = Array(Set(item.pulses + item.quantityRecords.map(\.pulse) + item.rawVolumes.map(\.pulse)))
            .filter { !$0.isEmpty }
            .sorted()
        let quantities = Array(Set(item.quantities + item.quantityRecords.map(\.quantity) + item.rawVolumes.flatMap(\.quantities)))
            .filter { !$0.isEmpty }
            .sorted()
        let pulseText = pulses.isEmpty ? "No pulses" : pulses.prefix(4).joined(separator: ", ")
        let quantityText: String
        if quantities.isEmpty && hasDownloadableSource(item) {
            quantityText = "Auto variable"
        } else {
            quantityText = quantities.isEmpty ? "No variables" : quantities.prefix(4).joined(separator: ", ")
        }
        let countText: String
        if item.sourceType == "raw_volume_day" {
            if item.rawVolumes.isEmpty {
                countText = item.rootAttrs["file_count"].map { "\($0) files" } ?? "scan catalog"
            } else {
                countText = "\(item.rawVolumes.count) scan\(item.rawVolumes.count == 1 ? "" : "s")"
            }
        } else {
            countText = "single file"
        }
        return "\(pulseText) / \(quantityText) / \(countText)"
    }

    func radarDisplayName(_ radar: String) -> String {
        catalog.first { $0.radar == radar }?.radarDisplayName ?? radar
    }

    var availablePulses: [String] {
        guard let item = selectedItem else { return [] }
        let availableVolumes = availableVolumes(for: item)
        let volumePulses = availableVolumes.map(\.pulse)
        let recordPulses = item.quantityRecords
            .filter { record in
                item.rawVolumes.isEmpty || availableVolumes.contains { volume in
                    volume.pulse == record.pulse && volume.time == record.time
                }
            }
            .map(\.pulse)
        let fallbackPulses = item.rawVolumes.isEmpty ? item.pulses : []
        return Array(Set(fallbackPulses + recordPulses + volumePulses))
            .filter { !$0.isEmpty }
            .sorted()
    }

    var availableTimes: [String] {
        guard let item = selectedItem else { return [] }
        return availableTimes(for: item, pulse: selectedPulse)
    }

    var availableQuantities: [String] {
        guard let item = selectedItem else { return [] }
        return availableQuantities(for: item, pulse: selectedPulse, time: selectedTime)
    }

    var availableDatasets: [QuantityRecord] {
        guard let item = selectedItem else { return [] }
        return availableDatasets(for: item, pulse: selectedPulse, time: selectedTime, quantity: selectedQuantity)
    }

    var selectedFieldSummary: String {
        [selectedPulse, selectedTime, selectedQuantity, selectedDatasetSummary]
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }

    var selectedElevationText: String {
        selectedDatasetSummary
    }

    var selectedSourceSizeText: String {
        guard let item = selectedItem else { return "" }
        if item.sourceType == "raw_volume_day" {
            if let volume = selectedRawVolume(for: item) {
                return volume.fileSize > 0 ? CacheStatus.byteString(volume.fileSize) : "Scan HDF5"
            }
            if !item.rawVolumes.isEmpty {
                return "\(item.rawVolumes.count) scan\(item.rawVolumes.count == 1 ? "" : "s")"
            }
        }
        return CacheStatus.byteString(item.fileSize)
    }

    var selectedTimePositionText: String {
        let times = availableTimes
        guard !times.isEmpty else { return "0 / 0" }
        let index = times.firstIndex(of: selectedTime).map { $0 + 1 } ?? 0
        return "\(index) / \(times.count)"
    }

    var canStepTime: Bool {
        availableTimes.count > 1
    }

    var selectedSourceURLString: String {
        guard let item = selectedItem else { return "" }
        return selectedSourceURL(for: item)?.absoluteString ?? ""
    }

    var selectedFieldAvailabilityText: String? {
        guard let item = selectedItem else { return "No catalog item selected." }
        if availablePulses.isEmpty {
            return "No pulse or scan metadata is available for \(item.title)."
        }
        if availableTimes.isEmpty {
            return "No scan times are available for \(item.title) \(selectedPulse)."
        }
        if availableQuantities.isEmpty && !canAutoSelectFileQuantity {
            return "No variables are available for \(item.title) \(selectedPulse) \(selectedTime)."
        }
        return nil
    }

    var selectedScanReadinessText: String {
        if let selectedFieldAvailabilityText {
            return selectedFieldAvailabilityText
        }
        if isDownloading {
            return "Downloading source"
        }
        if isRendering {
            return "Rendering"
        }
        if frame != nil {
            return "Rendered"
        }
        return "Ready to render"
    }

    var selectedCacheSummaryText: String {
        selectedCacheStatusText
    }

    var canAutoSelectFileQuantity: Bool {
        guard let item = selectedItem else { return false }
        return hasDownloadableSource(item) || cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) != nil
    }

    var selectedSourceDiagnosticRows: [SourceDiagnosticRow] {
        guard let item = selectedItem else { return [] }
        var rows = [
            SourceDiagnosticRow(label: "Radar", value: item.radarDisplayName),
            SourceDiagnosticRow(label: "Date", value: item.formattedDate),
            SourceDiagnosticRow(label: "Pulse", value: selectedPulse.isEmpty ? "Any" : selectedPulse),
            SourceDiagnosticRow(label: "Time", value: selectedTime.isEmpty ? "Auto" : selectedTime),
            SourceDiagnosticRow(label: "Variable", value: selectedQuantity.isEmpty ? "Auto" : selectedQuantity),
            SourceDiagnosticRow(label: "Elevation", value: selectedDatasetSummary),
            SourceDiagnosticRow(label: "Source", value: item.sourceType == "raw_volume_day" ? "Raw volume day" : "Aggregate day"),
            SourceDiagnosticRow(label: "Size", value: selectedSourceSizeText.isEmpty ? "Unknown" : selectedSourceSizeText),
            SourceDiagnosticRow(label: "Cache", value: selectedCacheStatusText),
        ]

        if let spatial = item.spatialMetadata,
           let latitude = spatial.latitude,
           let longitude = spatial.longitude {
            var siteText = String(format: "%.4f, %.4f", latitude, longitude)
            if let heightM = spatial.heightM {
                siteText += String(format: ", %.0f m", heightM)
            }
            rows.append(SourceDiagnosticRow(label: "Radar site", value: siteText))
        }

        if let frame {
            if showDataID {
                rows.append(SourceDiagnosticRow(label: "Data ID", value: frame.dataFingerprint))
            }
            rows.append(SourceDiagnosticRow(label: "Decoded", value: "\(frame.sourceShape.first ?? 0)x\(frame.sourceShape.dropFirst().first ?? 0)"))
            rows.append(SourceDiagnosticRow(label: "Rendered", value: "\(frame.rows)x\(frame.columns), \(frame.palette)"))
            if let min = frame.stats.scaleMin, let max = frame.stats.scaleMax {
                rows.append(SourceDiagnosticRow(label: "Display", value: String(format: "%.2f to %.2f", min, max)))
            }
            if frame.noiseFloor.enabled {
                let margin = frame.noiseFloor.marginDb.map { String(format: "+%.1f dB", $0) } ?? ""
                let method = frame.noiseFloor.method.isEmpty ? "estimated" : frame.noiseFloor.method
                let source = frame.noiseFloor.sourceQuantity.map { " \($0) gate" } ?? ""
                rows.append(SourceDiagnosticRow(
                    label: "Noise floor",
                    value: "\(method)\(source) \(frame.noiseFloor.operation) \(margin), \(frame.noiseFloor.maskedCount) masked"
                ))
            }
            if frame.backgroundModel.applied {
                rows.append(SourceDiagnosticRow(
                    label: "Background model",
                    value: "\(frame.backgroundModel.maskedCount) masked"
                ))
            } else if frame.backgroundModel.enabled, let reason = frame.backgroundModel.reason {
                rows.append(SourceDiagnosticRow(label: "Background model", value: reason))
            }
        }

        return rows
    }

    func loadCatalog() async {
        isLoadingCatalog = true
        warningMessage = nil
        defer {
            isLoadingCatalog = false
            hasCompletedInitialLoad = true
        }
        do {
            _ = try? cache.prune()
            cacheStatus = cache.status()
            if let root = try? await catalogService.fetchPVOLRootCatalog() {
                catalogRadarAvailability = Dictionary(uniqueKeysWithValues: root.radars.map { ($0.radar, $0) })
            } else {
                catalogRadarAvailability = [:]
            }
            catalog = try await catalogService.fetchCatalog()
            loadedCoverageYears = []
            let launchDefaultSelection = await applyLaunchDefaultSelectionIfNeeded()
            if selectedItemID == nil {
                selectedItemID = latestCatalogItem()?.id ?? catalog.first?.id
            }
            normalizeSelection(preferLatestTime: launchDefaultSelection?.preferLatestTime == true)
            await hydrateSelectedItemIfNeeded()
            if let launchDefaultSelection {
                normalizeSelection(resetDataset: launchDefaultSelection.preferLatestTime, preferLatestTime: launchDefaultSelection.preferLatestTime)
            }
            statusMessage = launchDefaultSelection?.statusText ?? (catalog.isEmpty ? "Catalog loaded but contained no items." : "Loaded \(catalog.count) catalog item\(catalog.count == 1 ? "" : "s").")
            if autoRenderEnabled {
                await renderImmediately()
            }
        } catch {
            statusMessage = "Catalog unavailable."
            warningMessage = error.localizedDescription
        }
    }

    func itemSelectionChanged() {
        prepareForSelectionChange()
        normalizeSelection(resetDataset: true)
        Task {
            await hydrateSelectedItemIfNeeded()
            if autoRenderEnabled {
                await renderImmediately()
            }
        }
    }

    func fieldSelectionChanged(resetDataset: Bool = false) {
        applyFieldSelectionChange(resetDataset: resetDataset)
    }

    func selectPulse(_ pulse: String) {
        guard availablePulses.contains(pulse) else {
            rejectUnavailableSelection(kind: "pulse", value: pulse)
            return
        }
        let preference = selectedDatasetPreference()
        pendingDatasetPreference = preference
        selectedPulse = pulse
        applyFieldSelectionChange(preferredDataset: preference)
    }

    func selectTime(_ time: String) {
        guard availableTimes.contains(time) else {
            rejectUnavailableSelection(kind: "time", value: time)
            return
        }
        let preference = selectedDatasetPreference()
        pendingDatasetPreference = preference
        selectedTime = time
        applyFieldSelectionChange(preferredDataset: preference)
    }

    func selectQuantity(_ quantity: String) {
        guard availableQuantities.contains(quantity) else {
            rejectUnavailableSelection(kind: "variable", value: quantity)
            return
        }
        let preference = selectedDatasetPreference()
        pendingDatasetPreference = preference
        selectedQuantity = quantity
        applyFieldSelectionChange(preferredDataset: preference)
    }

    func selectDataset(_ dataset: String) {
        guard availableDatasets.contains(where: { $0.dataset == dataset }) else {
            rejectUnavailableSelection(kind: "elevation", value: dataset)
            return
        }
        selectedDataset = dataset
        fieldSelectionChanged()
    }

    private func applyFieldSelectionChange(
        resetDataset: Bool = false,
        preferredDataset: DatasetSelectionPreference? = nil
    ) {
        prepareForSelectionChange(clearFrame: false)
        normalizeSelection(resetDataset: resetDataset, preferredDataset: preferredDataset)
        recordCurrentSelection()
        scheduleRender()
    }

    func stepTime(by delta: Int) {
        let times = availableTimes
        guard !times.isEmpty else { return }
        let currentIndex = times.firstIndex(of: selectedTime) ?? 0
        let nextIndex = (currentIndex + delta + times.count) % times.count
        let preference = selectedDatasetPreference()
        pendingDatasetPreference = preference
        selectedTime = times[nextIndex]
        applyFieldSelectionChange(preferredDataset: preference)
    }

    private func rejectUnavailableSelection(kind: String, value: String) {
        normalizeSelection()
        warningMessage = "Unavailable \(kind): \(value)."
        statusMessage = "Selection adjusted to available data."
    }

    func selectCatalogItem(_ item: CatalogItem) {
        selectedItemID = item.id
        itemSelectionChanged()
        recordCurrentSelection()
    }

    func loadCoverageForCurrentSearch() async {
        guard !isLoadingCoverage else { return }
        let radar = catalogSearch.radar
        guard !radar.isEmpty else { return }
        let years = yearsForCurrentSearch(radar: radar)
        let missingYears = years.filter { !loadedCoverageYears.contains(Self.coverageKey(radar: radar, year: $0)) }
        guard !missingYears.isEmpty else { return }

        isLoadingCoverage = true
        defer { isLoadingCoverage = false }
        do {
            statusMessage = "Loading \(radarDisplayName(radar)) \(missingYears.joined(separator: ", ")) coverage..."
            let items = try await catalogService.fetchCoverageDays(forRadar: radar, years: missingYears)
            mergeCatalogItems(items)
            for year in missingYears {
                loadedCoverageYears.insert(Self.coverageKey(radar: radar, year: year))
            }
            statusMessage = "Loaded \(items.count) day\(items.count == 1 ? "" : "s") for \(radarDisplayName(radar))."
        } catch {
            statusMessage = "Coverage unavailable for \(radarDisplayName(radar))."
            warningMessage = error.localizedDescription
        }
    }

    func resetCatalogSearch() {
        catalogSearch = CatalogSearchCriteria()
    }

    func setCatalogSearchToCurrentRadar() {
        catalogSearch.radar = selectedItem?.radar ?? ""
        if let year = selectedItem.flatMap({ Self.yearString(from: $0.date) }) {
            catalogSearch.year = year
        }
    }

    func clearCatalogDateFilters() {
        catalogSearch.startDate = ""
        catalogSearch.endDate = ""
    }

    func setCatalogSearchToFirstDay() {
        guard let range = catalogDateRange else { return }
        catalogSearch.startDate = CatalogItem.formattedDate(range.start)
        catalogSearch.endDate = CatalogItem.formattedDate(range.start)
    }

    func setCatalogSearchToLatestDay() {
        guard let range = catalogDateRange else { return }
        catalogSearch.startDate = CatalogItem.formattedDate(range.end)
        catalogSearch.endDate = CatalogItem.formattedDate(range.end)
    }

    func selectLatestPublishedDay() -> Bool {
        guard let item = latestCatalogItem() else { return false }
        selectCatalogItem(item)
        return true
    }

    func selectLatestUploadedDay() -> Bool {
        selectLatestPublishedDay()
    }

    func selectNearestRadarLatest() async -> Bool {
        statusMessage = "Finding nearest radar..."
        let location = await locationProvider.requestCurrentLocation(timeout: 4)
        if let location,
           let nearest = nearestRadar(near: location),
           let item = latestCatalogItem(forRadar: nearest.radar) {
            selectCatalogItem(item)
            statusMessage = "Loaded \(item.title), latest day from nearest radar (\(Self.distanceText(nearest.distanceMeters)) away)."
            return true
        }

        guard let item = latestCatalogItem() else { return false }
        selectCatalogItem(item)
        statusMessage = "Location unavailable. Loaded \(item.title), latest available day."
        return true
    }

    func applyRecentSelection(_ recent: RecentCatalogSelection) -> Bool {
        guard let item = catalog.first(where: { $0.id == recent.itemID }) else { return false }
        selectedItemID = item.id
        selectedPulse = recent.pulse
        selectedTime = recent.time
        selectedQuantity = recent.quantity
        selectedDataset = recent.dataset
        prepareForSelectionChange()
        normalizeSelection(resetDataset: false)
        recordCurrentSelection()
        Task {
            await hydrateSelectedItemIfNeeded()
            if autoRenderEnabled {
                await renderImmediately()
            }
        }
        return true
    }

    func filtersChanged() {
        scheduleRender()
    }

    private func scheduleRender() {
        guard autoRenderEnabled else { return }
        renderDebounceTask?.cancel()
        statusMessage = selectedFieldSummary.isEmpty ?
            "Queued render." :
            "Queued render for \(selectedFieldSummary)."
        renderDebounceTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: AppConfiguration.renderDebounceNanoseconds)
            guard !Task.isCancelled else { return }
            await self?.runScheduledRender()
        }
    }

    private func runScheduledRender() async {
        renderDebounceTask = nil
        await renderCurrent()
    }

    private func renderImmediately() async {
        renderDebounceTask?.cancel()
        renderDebounceTask = nil
        await renderCurrent()
    }

    func downloadSelectedAggregate() async {
        guard selectedItem != nil else {
            warningMessage = RadarAppError.noCatalogSelection.localizedDescription
            return
        }
        await hydrateSelectedItemIfNeeded()
        guard let item = selectedItem else {
            warningMessage = RadarAppError.noCatalogSelection.localizedDescription
            return
        }
        isDownloading = true
        warningMessage = nil
        statusMessage = "Downloading \(item.title) \(selectedPulse) \(selectedTime)..."
        defer {
            isDownloading = false
            cacheStatus = cache.status()
        }

        do {
            let localURL = try await cache.downloadSelectedSource(for: item, pulse: selectedPulse, time: selectedTime)
            statusMessage = "Cached \(localURL.lastPathComponent)."
            await renderImmediately()
        } catch {
            statusMessage = "Source download failed."
            warningMessage = error.localizedDescription
        }
    }

    func clearCache() {
        do {
            cacheStatus = try cache.clear()
            frame = nil
            identifyResult = nil
            statusMessage = "Cleared raw cache."
        } catch {
            warningMessage = error.localizedDescription
        }
    }

    func renderCurrent() async {
        guard selectedItem != nil else { return }
        renderRequestID += 1
        let requestID = renderRequestID
        await hydrateSelectedItemIfNeeded()
        guard requestID == renderRequestID else { return }
        guard let item = selectedItem else { return }
        normalizeSelection()
        if let fieldAvailabilityText = selectedFieldAvailabilityText {
            frame = nil
            identifyResult = nil
            warningMessage = nil
            statusMessage = fieldAvailabilityText
            return
        }

        isRendering = true
        defer {
            if requestID == renderRequestID {
                isRendering = false
            }
        }

        let selection = FieldSelection(
            pulse: selectedPulse,
            time: selectedTime,
            quantity: selectedQuantity,
            dataset: selectedDataset.isEmpty ? nil : selectedDataset,
            cappiHeightM: filters.cappiHeightM
        )

        let renderedFrame: PPIFrame
        let localURL: URL
        do {
            localURL = try await cachedOrDownloadSource(for: item, selection: selection, requestID: requestID)
        } catch {
            guard requestID == renderRequestID else { return }
            frame = nil
            warningMessage = error.localizedDescription
            statusMessage = "Source download failed for \(item.title) \(selectedFieldSummary)."
            return
        }
        guard requestID == renderRequestID else { return }
        normalizeSelection()
        let readSelection = FieldSelection(
            pulse: selectedPulse,
            time: selectedTime,
            quantity: selectedQuantity,
            dataset: selectedDataset.isEmpty ? nil : selectedDataset,
            cappiHeightM: filters.cappiHeightM
        )
        let readItem = selectedItem ?? item

        do {
            renderedFrame = try await renderWorker.renderFrame(
                from: localURL,
                item: readItem,
                selection: readSelection,
                filters: filters,
                backgroundModels: backgroundModels
            )
            warningMessage = nil
        } catch {
            guard requestID == renderRequestID else { return }
            frame = nil
            warningMessage = error.localizedDescription
            statusMessage = "HDF5 decode failed for \(item.title) \(selectedFieldSummary)."
            return
        }
        guard requestID == renderRequestID else { return }
        frame = renderedFrame
        identifyResult = nil
        cacheStatus = cache.status()
        statusMessage = "Rendered \(item.title) \(selectedFieldSummary)."
        if mapSettings.isEnabled {
            await refreshMapSnapshot(force: true)
        }
    }

    func identify(row: Int, column: Int) {
        guard let frame else { return }
        identifyResult = RadarRenderer().identify(frame: frame, row: row, column: column)
    }

    func refreshMapSnapshot(force: Bool = false) async {
        guard mapSettings.isEnabled else {
            mapSnapshotImage = nil
            mapStatusMessage = "Map off"
            return
        }
        guard let frame else {
            mapSnapshotImage = nil
            mapStatusMessage = MapSnapshotError.noFrame.localizedDescription
            return
        }
        if !force, mapSnapshotImage != nil {
            return
        }

        isLoadingMapSnapshot = true
        mapStatusMessage = "Loading map..."
        defer { isLoadingMapSnapshot = false }

        do {
            mapSnapshotImage = try await RadarMapSnapshotter.snapshot(for: frame, settings: mapSettings)
            mapStatusMessage = "Map ready"
        } catch {
            mapSnapshotImage = nil
            mapStatusMessage = error.localizedDescription
        }
    }

    func renderVideoFramesForCurrentSelection() async throws -> [PPIFrame] {
        let plan = try await makeVideoExportPlan(mode: .fast)
        var frames: [PPIFrame] = []
        _ = try await renderVideoFrames(
            for: plan,
            skipTimes: [],
            shouldStop: { false },
            onFrame: { frame, _, _ in
                frames.append(frame)
                return nil
            }
        )
        guard !frames.isEmpty else {
            throw VideoExportError.noFrames
        }
        videoExportProgress = "Encoding \(frames.count) frames..."
        return frames
    }

    func makeVideoExportPlan(mode: VideoExportMode) async throws -> VideoExportPlan {
        guard selectedItem != nil else {
            throw RadarAppError.noCatalogSelection
        }

        await hydrateSelectedItemIfNeeded()
        guard let item = selectedItem else {
            throw RadarAppError.noCatalogSelection
        }
        normalizeSelection()

        let exportPulse = selectedPulse
        let exportQuantity = selectedQuantity
        let exportDataset = selectedDataset
        let exportCappiHeightM = filters.cappiHeightM
        let exportFilters = filters
        let exportTimes = availableTimes(for: item, pulse: exportPulse)
        let datasetPreference = selectedDatasetPreference()
        guard exportTimes.count > 1 else {
            throw VideoExportError.notEnoughFrames
        }

        let frameRequests = exportTimes.enumerated().compactMap { index, time -> VideoExportFrameRequest? in
            let quantities = availableQuantities(for: item, pulse: exportPulse, time: time)
            if !exportQuantity.isEmpty, !quantities.isEmpty, !quantities.contains(exportQuantity) {
                return nil
            }
            let records = availableDatasets(for: item, pulse: exportPulse, time: time, quantity: exportQuantity)
            let dataset = resolvedDataset(
                selectedDataset: exportDataset,
                preference: datasetPreference,
                records: records
            )
            if !exportDataset.isEmpty, !records.isEmpty, dataset == nil {
                return nil
            }
            return VideoExportFrameRequest(
                index: index,
                time: time,
                selection: FieldSelection(
                    pulse: exportPulse,
                    time: time,
                    quantity: exportQuantity,
                    dataset: dataset,
                    cappiHeightM: exportCappiHeightM
                )
            )
        }

        guard !frameRequests.isEmpty else {
            throw VideoExportError.noFrames
        }

        return VideoExportPlan(
            mode: mode,
            quality: mode.quality,
            item: item,
            pulse: exportPulse,
            quantity: exportQuantity,
            dataset: exportDataset,
            filters: exportFilters,
            requestedTimes: exportTimes,
            frameRequests: frameRequests
        )
    }

    func renderVideoFramesForCurrentSelection(
        skipTimes: Set<String> = [],
        shouldStop: @escaping () -> Bool,
        onFrame: @escaping (PPIFrame, Int, Int) throws -> Void
    ) async throws -> VideoFrameExportSummary {
        let plan = try await makeVideoExportPlan(mode: .resumeSafe)
        return try await renderVideoFrames(
            for: plan,
            skipTimes: skipTimes,
            shouldStop: shouldStop
        ) { frame, index, total in
            try onFrame(frame, index, total)
            return nil
        }
    }

    func renderVideoFrames(
        for plan: VideoExportPlan,
        skipTimes: Set<String> = [],
        shouldStop: @escaping () -> Bool,
        onFrame: @escaping (PPIFrame, Int, Int) throws -> VideoFrameWriteTiming?
    ) async throws -> VideoFrameExportSummary {
        renderRequestID += 1
        let requestID = renderRequestID
        isExportingVideo = true
        videoExportProgress = "\(plan.mode.statusName) export 0 / \(plan.requestedTimes.count)"
        let startedAt = Date()
        var metrics = VideoExportMetrics()
        var lastProgressAt = Date.distantPast
        defer {
            isExportingVideo = false
            cacheStatus = cache.status()
        }

        var renderedFrames = 0
        var failures = plan.skippedFrameCount
        var stoppedEarly = false
        var prefetchTasks: [String: Task<URL, Error>] = [:]

        func updateProgress(_ message: String, index: Int, force: Bool = false) {
            let now = Date()
            if force || index % 5 == 0 || now.timeIntervalSince(lastProgressAt) >= 0.25 {
                videoExportProgress = message
                lastProgressAt = now
            }
        }

        func schedulePrefetches(after requestIndex: Int) {
            let window = 2
            let upperBound = min(plan.frameRequests.count, requestIndex + 1 + window)
            guard requestIndex + 1 < upperBound else { return }
            for nextIndex in (requestIndex + 1)..<upperBound {
                let request = plan.frameRequests[nextIndex]
                guard !skipTimes.contains(request.time),
                      cache.existingSourceURL(for: plan.item, pulse: request.selection.pulse, time: request.selection.time) == nil,
                      prefetchTasks[request.time] == nil else {
                    continue
                }
                prefetchTasks[request.time] = Task {
                    try await self.cache.downloadSelectedSource(
                        for: plan.item,
                        pulse: request.selection.pulse,
                        time: request.selection.time
                    )
                }
            }
        }

        func localSource(for request: VideoExportFrameRequest) async throws -> URL {
            if let localURL = cache.existingSourceURL(for: plan.item, pulse: request.selection.pulse, time: request.selection.time) {
                return localURL
            }
            if let task = prefetchTasks.removeValue(forKey: request.time) {
                return try await task.value
            }
            return try await cachedOrDownloadSource(for: plan.item, selection: request.selection, requestID: requestID)
        }

        for (requestIndex, request) in plan.frameRequests.enumerated() {
            if shouldStop() {
                stoppedEarly = true
                break
            }
            guard requestID == renderRequestID else {
                if shouldStop() {
                    stoppedEarly = true
                    break
                }
                throw VideoExportError.cancelled
            }
            if skipTimes.contains(request.time) {
                renderedFrames += 1
                updateProgress(
                    "Using saved frame \(request.index + 1) / \(plan.requestedTimes.count)",
                    index: request.index
                )
                await Task.yield()
                continue
            }
            schedulePrefetches(after: requestIndex)

            do {
                let downloadStart = Date()
                let localURL = try await localSource(for: request)
                metrics.downloadSeconds += Date().timeIntervalSince(downloadStart)
                if shouldStop() {
                    stoppedEarly = true
                    break
                }
                guard requestID == renderRequestID else {
                    if shouldStop() {
                        stoppedEarly = true
                        break
                    }
                    throw VideoExportError.cancelled
                }
                let renderResult = try await renderWorker.renderFrameWithTimings(
                    from: localURL,
                    item: plan.item,
                    selection: request.selection,
                    filters: plan.filters,
                    backgroundModels: backgroundModels
                )
                metrics.hdf5ReadSeconds += renderResult.hdf5ReadSeconds
                metrics.radarRenderSeconds += renderResult.radarRenderSeconds
                if shouldStop() {
                    stoppedEarly = true
                    break
                }
                if let writeTiming = try onFrame(renderResult.frame, request.index + 1, plan.requestedTimes.count) {
                    metrics.imageDrawSeconds += writeTiming.drawSeconds
                    metrics.encodeSeconds += writeTiming.encodeSeconds
                }
                renderedFrames += 1
                updateProgress(
                    "Rendering and encoding \(plan.mode.statusName) export \(request.index + 1) / \(plan.requestedTimes.count)",
                    index: request.index
                )
            } catch {
                if shouldStop() || (error as? VideoExportError) == .backgroundTimeExpired {
                    stoppedEarly = true
                    break
                }
                failures += 1
                warningMessage = error.localizedDescription
                updateProgress(
                    "Skipped \(request.index + 1) / \(plan.requestedTimes.count)",
                    index: request.index,
                    force: true
                )
            }
            await Task.yield()
        }
        prefetchTasks.values.forEach { $0.cancel() }

        guard renderedFrames > 0 else {
            throw VideoExportError.noFrames
        }
        metrics.totalSeconds = Date().timeIntervalSince(startedAt)
        videoExportProgress = stoppedEarly ?
            "Finishing partial MP4..." :
            (failures == 0 ?
                "Finishing MP4..." :
                "Finishing \(renderedFrames) frames, skipped \(failures)...")
        return VideoFrameExportSummary(
            requestedFrames: plan.requestedTimes.count,
            renderedFrames: renderedFrames,
            skippedFrames: failures,
            stoppedEarly: stoppedEarly,
            metrics: metrics
        )
    }

    func cancelVideoExportForBackgroundExpiration() {
        guard isExportingVideo else { return }
        renderRequestID += 1
        videoExportProgress = "Finishing partial MP4 before iOS suspends export..."
        warningMessage = "iOS background time expired. Finishing a partial MP4 if enough frames were written."
    }

    private func applyLaunchDefaultSelectionIfNeeded() async -> LaunchDefaultSelection? {
        guard !hasAppliedLaunchDefaultSelection else { return nil }
        hasAppliedLaunchDefaultSelection = true
        guard selectedItemID == nil, !catalog.isEmpty else { return nil }

        if let recent = recentSelections.first,
           let item = catalog.first(where: { $0.id == recent.itemID }) {
            applyStoredSelection(recent, item: item)
            return LaunchDefaultSelection(
                itemID: item.id,
                statusText: "Restored \(item.title) from recent selections.",
                preferLatestTime: false
            )
        }

        statusMessage = "Finding nearest radar..."
        let location = await locationProvider.requestCurrentLocation(timeout: 4)
        if let location,
           let nearest = nearestRadar(near: location),
           let item = latestCatalogItem(forRadar: nearest.radar) {
            selectedItemID = item.id
            return LaunchDefaultSelection(
                itemID: item.id,
                statusText: "Loaded \(item.title), latest day from nearest radar (\(Self.distanceText(nearest.distanceMeters)) away)."
            )
        }

        guard let item = latestCatalogItem() else { return nil }
        selectedItemID = item.id
        let reason = location == nil ? "Location unavailable" : "Catalog has no radar coordinates"
        return LaunchDefaultSelection(
            itemID: item.id,
            statusText: "\(reason). Loaded \(item.title), latest available day."
        )
    }

    private func nearestRadar(near location: CLLocation) -> (radar: String, distanceMeters: CLLocationDistance)? {
        let groupedByRadar = Dictionary(grouping: catalog, by: \.radar)
        return groupedByRadar.compactMap { radar, items -> (radar: String, distanceMeters: CLLocationDistance)? in
            guard let radarLocation = items.compactMap(\.spatialLocation).first else { return nil }
            return (radar: radar, distanceMeters: radarLocation.distance(from: location))
        }
        .min { $0.distanceMeters < $1.distanceMeters }
    }

    private func prepareForSelectionChange(clearFrame: Bool = true) {
        renderRequestID += 1
        if clearFrame {
            frame = nil
        }
        identifyResult = nil
        warningMessage = nil
        if let item = selectedItem {
            statusMessage = "Selected \(item.title)."
        }
    }

    private func latestCatalogItem(forRadar radar: String? = nil) -> CatalogItem? {
        catalog
            .filter { radar == nil || $0.radar == radar }
            .max { lhs, rhs in
                if lhs.date != rhs.date { return lhs.date < rhs.date }
                if lhs.modifiedTime != rhs.modifiedTime { return lhs.modifiedTime < rhs.modifiedTime }
                return lhs.id < rhs.id
            }
    }

    private func sortCatalogItems(_ lhs: CatalogItem, _ rhs: CatalogItem) -> Bool {
        switch catalogSearch.sortMode {
        case .newestFirst:
            return isNewerCatalogItem(lhs, than: rhs)
        case .radarThenNewest:
            let lhsRadar = lhs.radarDisplayName.localizedCaseInsensitiveCompare(rhs.radarDisplayName)
            if lhsRadar != .orderedSame {
                return lhsRadar == .orderedAscending
            }
            return isNewerCatalogItem(lhs, than: rhs)
        case .cachedFirst:
            let lhsCached = isCatalogItemCached(lhs)
            let rhsCached = isCatalogItemCached(rhs)
            if lhsCached != rhsCached {
                return lhsCached
            }
            return isNewerCatalogItem(lhs, than: rhs)
        }
    }

    private func isNewerCatalogItem(_ lhs: CatalogItem, than rhs: CatalogItem) -> Bool {
        if lhs.date != rhs.date { return lhs.date > rhs.date }
        if lhs.modifiedTime != rhs.modifiedTime { return lhs.modifiedTime > rhs.modifiedTime }
        let lhsTitle = lhs.title.localizedCaseInsensitiveCompare(rhs.title)
        if lhsTitle != .orderedSame { return lhsTitle == .orderedAscending }
        return lhs.id < rhs.id
    }

    private func applyStoredSelection(_ recent: RecentCatalogSelection, item: CatalogItem) {
        selectedItemID = item.id
        selectedPulse = recent.pulse
        selectedTime = recent.time
        selectedQuantity = recent.quantity
        selectedDataset = recent.dataset
    }

    private func recordCurrentSelection() {
        guard let item = selectedItem else { return }
        let selection = RecentCatalogSelection(
            itemID: item.id,
            radar: item.radar,
            radarDisplayName: item.radarDisplayName,
            date: item.date,
            pulse: selectedPulse,
            time: selectedTime,
            quantity: selectedQuantity,
            dataset: selectedDataset,
            selectedAt: Date()
        )
        var updated = recentSelections.filter { $0.itemID != selection.itemID }
        updated.insert(selection, at: 0)
        recentSelections = Array(updated.prefix(10))
        recentSelectionStore.saveRecentSelections(recentSelections)
    }

    private func mergeCatalogItems(_ items: [CatalogItem]) {
        guard !items.isEmpty else { return }
        var byID = Dictionary(uniqueKeysWithValues: catalog.map { ($0.id, $0) })
        for item in items {
            if let existing = byID[item.id], !existing.rawVolumes.isEmpty, item.rawVolumes.isEmpty {
                continue
            }
            byID[item.id] = item
        }
        catalog = Array(byID.values).sorted {
            ($0.radar, $0.date, $0.rawVolumeCatalogKey) < ($1.radar, $1.date, $1.rawVolumeCatalogKey)
        }
    }

    private func yearsForCurrentSearch(radar: String) -> [String] {
        let start = Self.compactCatalogDate(catalogSearch.startDate)
        let end = Self.compactCatalogDate(catalogSearch.endDate)
        let startYear = start.flatMap { Self.yearString(from: $0) }
        let endYear = end.flatMap { Self.yearString(from: $0) }

        if let startYear, let endYear, let startInt = Int(startYear), let endInt = Int(endYear) {
            return (min(startInt, endInt)...max(startInt, endInt)).map(String.init)
        }
        if let startYear { return [startYear] }
        if let endYear { return [endYear] }
        if !catalogSearch.year.isEmpty {
            return [catalogSearch.year]
        }
        if let rootYears = catalogRadarAvailability[radar]?.years, !rootYears.isEmpty {
            return rootYears.sorted(by: >)
        }
        if let latestLoadedYear = catalog
            .filter({ $0.radar == radar })
            .compactMap({ Self.yearString(from: $0.date) })
            .max() {
            return [latestLoadedYear]
        }
        return []
    }

    private static func yearString(from compactDate: String) -> String? {
        guard compactDate.count >= 4 else { return nil }
        return String(compactDate.prefix(4))
    }

    private static func coverageKey(radar: String, year: String) -> String {
        "\(radar):\(year)"
    }

    private func availableVolumes(for item: CatalogItem) -> [RawVolumeRecord] {
        item.rawVolumes.filter { isAvailableVolume($0, for: item) }
    }

    private func availableTimes(for item: CatalogItem, pulse: String) -> [String] {
        let availableVolumes = availableVolumes(for: item)
        let fromRecords = item.quantityRecords
            .filter { pulse.isEmpty || $0.pulse == pulse }
            .filter { record in
                item.rawVolumes.isEmpty || availableVolumes.contains { volume in
                    volume.pulse == record.pulse && volume.time == record.time
                }
            }
            .map(\.time)
            .filter { !$0.isEmpty }
        let fromVolumes = availableVolumes
            .filter { pulse.isEmpty || $0.pulse == pulse }
            .map(\.time)
            .filter { !$0.isEmpty }
        if !fromRecords.isEmpty || !fromVolumes.isEmpty {
            return Array(Set(fromRecords + fromVolumes)).sorted()
        }

        let fromPulseMap: [String]
        if item.rawVolumes.isEmpty {
            fromPulseMap = pulse.isEmpty ? item.timesByPulse.values.flatMap { $0 } : item.timesByPulse[pulse] ?? []
        } else {
            fromPulseMap = []
        }
        let fallbackTimes = pulse.isEmpty || item.rawVolumes.isEmpty ? item.times : []
        return Array(Set(fallbackTimes + fromPulseMap))
            .filter { !$0.isEmpty }
            .sorted()
    }

    private func availableQuantities(for item: CatalogItem, pulse: String, time: String) -> [String] {
        let availableVolumes = availableVolumes(for: item)
        let fromRecords = item.quantityRecords
            .filter { pulse.isEmpty || $0.pulse == pulse }
            .filter { time.isEmpty || $0.time == time }
            .filter { record in
                item.rawVolumes.isEmpty || availableVolumes.contains { volume in
                    volume.pulse == record.pulse && volume.time == record.time
                }
            }
            .map(\.quantity)
            .filter { !$0.isEmpty }
        let fromVolumes = availableVolumes
            .filter { pulse.isEmpty || $0.pulse == pulse }
            .filter { time.isEmpty || $0.time == time }
            .flatMap(\.quantities)
            .filter { !$0.isEmpty }
        let confirmed = Array(Set(fromRecords + fromVolumes)).sorted()
        if !confirmed.isEmpty {
            return confirmed
        }
        if item.sourceType == "raw_volume_day" || item.sourceType == "raw_volume_file" {
            return []
        }
        return Array(Set(item.quantities.filter { !$0.isEmpty })).sorted()
    }

    private func availableDatasets(
        for item: CatalogItem,
        pulse: String,
        time: String,
        quantity: String
    ) -> [QuantityRecord] {
        let availableVolumes = availableVolumes(for: item)
        let records = item.quantityRecords
            .filter { pulse.isEmpty || $0.pulse == pulse }
            .filter { time.isEmpty || $0.time == time }
            .filter { quantity.isEmpty || $0.quantity == quantity }
            .filter { record in
                item.rawVolumes.isEmpty || availableVolumes.contains { volume in
                    volume.pulse == record.pulse && volume.time == record.time
                }
            }
        return records.sorted {
            (datasetSortValue($0), $0.dataset) < (datasetSortValue($1), $1.dataset)
        }
    }

    private func cachedOrDownloadSource(for item: CatalogItem, selection: FieldSelection, requestID: Int) async throws -> URL {
        if let localURL = cache.existingSourceURL(for: item, pulse: selection.pulse, time: selection.time) {
            await applyInspectedMetadataIfAvailable(from: localURL, item: item, pulse: selection.pulse, time: selection.time)
            return localURL
        }

        if requestID == renderRequestID {
            isDownloading = true
            warningMessage = nil
            statusMessage = "Downloading raw HDF5 for \(item.title) \(selectedFieldSummary)..."
        }
        defer {
            if requestID == renderRequestID {
                isDownloading = false
                cacheStatus = cache.status()
            }
        }

        let localURL = try await cache.downloadSelectedSource(for: item, pulse: selection.pulse, time: selection.time)
        await applyInspectedMetadataIfAvailable(from: localURL, item: item, pulse: selection.pulse, time: selection.time)
        if requestID == renderRequestID {
            statusMessage = "Cached \(localURL.lastPathComponent)."
        }
        return localURL
    }

    private func applyInspectedMetadataIfAvailable(from fileURL: URL, item: CatalogItem, pulse: String, time: String) async {
        guard let records = try? await renderWorker.inspectFields(from: fileURL, item: item, pulse: pulse, time: time),
              !records.isEmpty,
              let index = catalog.firstIndex(where: { $0.id == item.id }) else {
            return
        }

        var updated = catalog[index]
        updated.quantityRecords.removeAll { $0.pulse == pulse && $0.time == time }
        updated.quantityRecords.append(contentsOf: records)

        let pulseSet = Set(updated.pulses + records.map(\.pulse)).filter { !$0.isEmpty }
        updated.pulses = Array(pulseSet).sorted()
        let timeSet = Set(updated.times + records.map(\.time)).filter { !$0.isEmpty }
        updated.times = Array(timeSet).sorted()

        let recordQuantities = Array(Set(records.map(\.quantity).filter { !$0.isEmpty })).sorted()
        for volumeIndex in updated.rawVolumes.indices
            where (pulse.isEmpty || updated.rawVolumes[volumeIndex].pulse == pulse) &&
            (time.isEmpty || updated.rawVolumes[volumeIndex].time == time) {
            updated.rawVolumes[volumeIndex].quantities = recordQuantities
        }

        updated.quantities = Array(Set(updated.quantityRecords.map(\.quantity) + updated.rawVolumes.flatMap(\.quantities)))
            .filter { !$0.isEmpty }
            .sorted()
        updated.quantitiesByPulse = Dictionary(grouping: updated.quantityRecords, by: \.pulse)
            .mapValues { Array(Set($0.map(\.quantity).filter { !$0.isEmpty })).sorted() }
            .filter { !$0.key.isEmpty && !$0.value.isEmpty }

        let quantityTimesByPulse = Dictionary(grouping: updated.quantityRecords, by: \.pulse)
            .mapValues { Set($0.map(\.time).filter { !$0.isEmpty }) }
        let volumeTimesByPulse = Dictionary(grouping: updated.rawVolumes.filter { isAvailableVolume($0, for: updated) }, by: \.pulse)
            .mapValues { Set($0.map(\.time).filter { !$0.isEmpty }) }
        var mergedTimesByPulse = updated.timesByPulse.mapValues { Set($0.filter { !$0.isEmpty }) }
        for (pulse, times) in quantityTimesByPulse {
            mergedTimesByPulse[pulse, default: []].formUnion(times)
        }
        for (pulse, times) in volumeTimesByPulse {
            mergedTimesByPulse[pulse, default: []].formUnion(times)
        }
        updated.timesByPulse = mergedTimesByPulse
            .mapValues { Array($0).sorted() }
            .filter { !$0.key.isEmpty && !$0.value.isEmpty }

        catalog[index] = updated
        normalizeSelection()
    }

    private var selectedDatasetSummary: String {
        if let record = availableDatasets.first(where: { $0.dataset == selectedDataset }) {
            if let elevation = record.elevationDeg {
                return "\(String(format: "%.2f", elevation))°"
            }
            if let height = record.nominalHeightM {
                return "\(Int(height)) m"
            }
            return "Elevation n/a"
        }
        return "Auto"
    }

    private var selectedCacheStatusText: String {
        guard let item = selectedItem else { return "No item" }
        guard let url = cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) else {
            return "Not cached"
        }
        return "Cached \(url.lastPathComponent)"
    }

    private func datasetSortValue(_ record: QuantityRecord) -> Double {
        if let elevation = record.elevationDeg {
            return elevation
        }
        if let height = record.nominalHeightM {
            return height
        }
        return Double.greatestFiniteMagnitude
    }

    private func selectedDatasetPreference() -> DatasetSelectionPreference? {
        guard let record = availableDatasets.first(where: { $0.dataset == selectedDataset }) else {
            return nil
        }
        return DatasetSelectionPreference(
            dataset: record.dataset,
            elevationDeg: record.elevationDeg,
            nominalHeightM: record.nominalHeightM
        )
    }

    private func resolvedDataset(
        selectedDataset: String,
        preference: DatasetSelectionPreference?,
        records: [QuantityRecord]
    ) -> String? {
        guard !records.isEmpty else {
            return selectedDataset.isEmpty ? nil : selectedDataset
        }

        if let preference,
           let elevation = preference.elevationDeg,
           let match = records.min(by: { lhs, rhs in
               abs((lhs.elevationDeg ?? .greatestFiniteMagnitude) - elevation) <
                   abs((rhs.elevationDeg ?? .greatestFiniteMagnitude) - elevation)
           }),
           let matchedElevation = match.elevationDeg,
           abs(matchedElevation - elevation) <= 0.05 {
            return match.dataset
        }

        if let preference,
           let height = preference.nominalHeightM,
           let match = records.min(by: { lhs, rhs in
               abs((lhs.nominalHeightM ?? .greatestFiniteMagnitude) - height) <
                   abs((rhs.nominalHeightM ?? .greatestFiniteMagnitude) - height)
           }),
           let matchedHeight = match.nominalHeightM,
           abs(matchedHeight - height) <= 1 {
            return match.dataset
        }

        if !selectedDataset.isEmpty, records.contains(where: { $0.dataset == selectedDataset }) {
            return selectedDataset
        }

        return selectedDataset.isEmpty ? records.first?.dataset : nil
    }

    private func applyDatasetPreference(_ preference: DatasetSelectionPreference?) -> Bool {
        guard let preference else { return false }
        let records = availableDatasets
        guard !records.isEmpty else { return false }

        if let elevation = preference.elevationDeg,
           let match = records.min(by: { lhs, rhs in
               abs((lhs.elevationDeg ?? .greatestFiniteMagnitude) - elevation) <
                   abs((rhs.elevationDeg ?? .greatestFiniteMagnitude) - elevation)
           }),
           let matchedElevation = match.elevationDeg,
           abs(matchedElevation - elevation) <= 0.05 {
            selectedDataset = match.dataset
            return true
        }

        if let height = preference.nominalHeightM,
           let match = records.min(by: { lhs, rhs in
               abs((lhs.nominalHeightM ?? .greatestFiniteMagnitude) - height) <
                   abs((rhs.nominalHeightM ?? .greatestFiniteMagnitude) - height)
           }),
           let matchedHeight = match.nominalHeightM,
           abs(matchedHeight - height) <= 1 {
            selectedDataset = match.dataset
            return true
        }

        if records.contains(where: { $0.dataset == preference.dataset }) {
            selectedDataset = preference.dataset
            return true
        }

        return false
    }

    private func selectedSourceURL(for item: CatalogItem) -> URL? {
        if item.sourceType == "raw_volume_day", let volume = selectedRawVolume(for: item) {
            return volume.downloadURL(publicBaseURL: AppConfiguration.publicBaseURL)
        }
        return item.aggregateURL(publicBaseURL: AppConfiguration.publicBaseURL)
    }

    private func hasDownloadableSource(_ item: CatalogItem) -> Bool {
        if item.sourceType == "raw_volume_day" {
            if item.rawVolumes.isEmpty {
                return item.rawVolumeCatalogDownloadURL(publicBaseURL: AppConfiguration.publicBaseURL) != nil
            }
            return item.rawVolumes.contains { isAvailableVolume($0, for: item) }
        }
        return item.aggregateURL(publicBaseURL: AppConfiguration.publicBaseURL) != nil
    }

    private func selectedRawVolume(for item: CatalogItem) -> RawVolumeRecord? {
        item.rawVolumes.first { volume in
            (selectedPulse.isEmpty || volume.pulse == selectedPulse) &&
                (selectedTime.isEmpty || volume.time == selectedTime) &&
                isAvailableVolume(volume, for: item)
        } ?? item.rawVolume(for: selectedPulse, time: selectedTime)
    }

    private func isAvailableVolume(_ volume: RawVolumeRecord, for item: CatalogItem) -> Bool {
        volume.downloadURL(publicBaseURL: AppConfiguration.publicBaseURL) != nil ||
            cache.fileManager.fileExists(atPath: cache.localVolumeURL(for: item, volume: volume).path)
    }

    private static func compactCatalogDate(_ value: String) -> String? {
        let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return nil }

        let parts = raw.split { !$0.isNumber }.map(String.init)
        if parts.count == 3 {
            if parts[0].count == 4 {
                return parts[0] + parts[1].leftPadded(to: 2) + parts[2].leftPadded(to: 2)
            }
            if parts[2].count == 4 {
                return parts[2] + parts[1].leftPadded(to: 2) + parts[0].leftPadded(to: 2)
            }
        }

        let digits = String(raw.filter(\.isNumber))
        return digits.count == 8 ? digits : raw.replacingOccurrences(of: "-", with: "")
    }

    private func normalizeSelection(
        resetDataset: Bool = false,
        preferLatestTime: Bool = false,
        preferredDataset: DatasetSelectionPreference? = nil
    ) {
        guard selectedItem != nil else { return }
        if !availablePulses.contains(selectedPulse) {
            selectedPulse = availablePulses.first ?? ""
        }
        if preferLatestTime, let latestTime = availableTimes.last {
            selectedTime = latestTime
        } else if !availableTimes.contains(selectedTime) {
            selectedTime = availableTimes.first ?? ""
        }
        if !availableQuantities.contains(selectedQuantity) {
            selectedQuantity = availableQuantities.first { $0.uppercased() == "DBZH" } ?? availableQuantities.first ?? ""
        }
        let datasetPreference = preferredDataset ?? pendingDatasetPreference
        if resetDataset {
            pendingDatasetPreference = nil
            selectedDataset = availableDatasets.first?.dataset ?? ""
        } else if applyDatasetPreference(datasetPreference) {
            if datasetPreference == pendingDatasetPreference {
                pendingDatasetPreference = nil
            }
        } else if !availableDatasets.isEmpty {
            if datasetPreference == pendingDatasetPreference {
                pendingDatasetPreference = nil
            }
            if !availableDatasets.contains(where: { $0.dataset == selectedDataset }) {
                selectedDataset = availableDatasets.first?.dataset ?? ""
            }
        }
        filters.cappiHeightM = filters.cappiHeightM
    }

    private func hydrateSelectedItemIfNeeded() async {
        guard let item = selectedItem else { return }
        guard item.sourceType == "raw_volume_day", item.rawVolumes.isEmpty else { return }
        do {
            statusMessage = "Loading scan catalog for \(item.title)..."
            let rawItems = try await catalogService.fetchRawVolumeCatalog(for: item)
            guard !rawItems.isEmpty else {
                statusMessage = "Day scan catalog has no published files for \(item.title)."
                return
            }
            let hydrated = item.hydrated(with: rawItems)
            if let index = catalog.firstIndex(where: { $0.id == item.id }) {
                catalog[index] = hydrated
            }
            normalizeSelection(resetDataset: true)
        } catch {
            statusMessage = "Day scan catalog unavailable for \(item.title)."
            warningMessage = error.localizedDescription
        }
    }

    private static func distanceText(_ meters: CLLocationDistance) -> String {
        if meters >= 1000 {
            return "\(Int((meters / 1000).rounded())) km"
        }
        return "\(Int(meters.rounded())) m"
    }
}

private extension CatalogItem {
    static func formattedDate(_ value: String) -> String {
        guard value.count == 8 else { return value }
        return "\(value.prefix(4))-\(value.dropFirst(4).prefix(2))-\(value.suffix(2))"
    }

    var searchText: String {
        ([
            title,
            radar,
            radarDisplayName,
            radarNum,
            date,
            formattedDate,
            validationStatus,
            sourceType,
        ] + pulses + quantities + quantityRecords.map(\.quantity) + quantityRecords.map(\.pulse) + rawVolumes.flatMap(\.quantities))
            .joined(separator: " ")
    }

    func matchesPulse(_ pulse: String) -> Bool {
        pulses.contains(pulse) ||
            quantityRecords.contains { $0.pulse == pulse } ||
            rawVolumes.contains { $0.pulse == pulse }
    }

    func matchesQuantity(_ quantity: String) -> Bool {
        quantities.contains(quantity) ||
            quantityRecords.contains { $0.quantity == quantity } ||
            rawVolumes.contains { $0.quantities.contains(quantity) }
    }

    var spatialLocation: CLLocation? {
        guard let latitude = spatialMetadata?.latitude,
              let longitude = spatialMetadata?.longitude,
              latitude.isFinite,
              longitude.isFinite,
              (-90...90).contains(latitude),
              (-180...180).contains(longitude) else {
            return nil
        }
        return CLLocation(latitude: latitude, longitude: longitude)
    }
}

private extension String {
    func leftPadded(to length: Int, with character: Character = "0") -> String {
        if count >= length { return self }
        return String(repeating: String(character), count: length - count) + self
    }
}

extension QuantityRecord {
    var datasetName: String {
        dataset.hasPrefix("dataset") ? dataset : "dataset\(dataset)"
    }
}
