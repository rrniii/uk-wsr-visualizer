import CoreLocation
import Foundation

enum AppConfiguration {
    static let publicBaseURL = URL(string: "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public")!
    static let publicCatalogURL = URL(string: "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json")!
    static let maxCacheBytes: Int64 = 8 * 1024 * 1024 * 1024
    static let cacheTTLSeconds: TimeInterval = 7 * 24 * 60 * 60
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

struct CatalogSearchCriteria: Hashable {
    var radar = ""
    var pulse = ""
    var startDate = ""
    var endDate = ""
    var text = ""
}

struct SourceDiagnosticRow: Identifiable, Hashable {
    var label: String
    var value: String

    var id: String { label }
}

struct LaunchDefaultSelection: Hashable {
    var itemID: String
    var statusText: String
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

struct CatalogService {
    var catalogURL: URL = AppConfiguration.publicCatalogURL

    func fetchCatalog() async throws -> [CatalogItem] {
        let (data, response) = try await URLSession.shared.data(from: catalogURL)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        let decoder = JSONDecoder()
        return try decoder.decode(CatalogEnvelope.self, from: data).items.sorted {
            ($0.radar, $0.date) < ($1.radar, $1.date)
        }
    }

    func fetchRawVolumeCatalog(for item: CatalogItem, publicBaseURL: URL = AppConfiguration.publicBaseURL) async throws -> [CatalogItem] {
        guard let url = item.rawVolumeCatalogDownloadURL(publicBaseURL: publicBaseURL) else {
            return []
        }
        let (data, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(CatalogEnvelope.self, from: data).items.sorted {
            ($0.pulses.first ?? "", $0.times.first ?? "", $0.objectKey) <
                ($1.pulses.first ?? "", $1.times.first ?? "", $1.objectKey)
        }
    }
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
final class VisualizerViewModel: ObservableObject {
    @Published var catalog: [CatalogItem] = []
    @Published var selectedItemID: String?
    @Published var selectedPulse = ""
    @Published var selectedTime = ""
    @Published var selectedQuantity = ""
    @Published var selectedDataset = ""
    @Published var filters = RadarFilterSet()
    @Published var frame: PPIFrame?
    @Published var identifyResult: IdentifyResult?
    @Published var isLoadingCatalog = false
    @Published var isDownloading = false
    @Published var isRendering = false
    @Published var statusMessage = "Load the public catalog to begin."
    @Published var warningMessage: String?
    @Published var cacheStatus = CacheStatus()
    @Published var catalogSearch = CatalogSearchCriteria()

    private let catalogService: CatalogService
    private let cache: RadarCache
    private let hdf5Reader: RadarVolumeReader
    private let locationProvider: DeviceLocationProviding
    private let renderer = RadarRenderer()
    private var renderRequestID = 0
    private var hasAppliedLaunchDefaultSelection = false

    init(
        catalogService: CatalogService = CatalogService(),
        cache: RadarCache = .live,
        hdf5Reader: RadarVolumeReader = NativeHDF5VolumeReader(),
        locationProvider: DeviceLocationProviding? = nil
    ) {
        self.catalogService = catalogService
        self.cache = cache
        self.hdf5Reader = hdf5Reader
        self.locationProvider = locationProvider ?? DeviceLocationProvider()
        self.cacheStatus = cache.status()
    }

    var selectedItem: CatalogItem? {
        guard let selectedItemID else { return nil }
        return catalog.first { $0.id == selectedItemID }
    }

    var catalogRadarOptions: [String] {
        Array(Set(catalog.map(\.radar).filter { !$0.isEmpty })).sorted {
            radarDisplayName($0) < radarDisplayName($1)
        }
    }

    var catalogPulseOptions: [String] {
        let criteria = catalogSearch
        let matchingItems = catalog.filter { item in
            if !criteria.radar.isEmpty && item.radar != criteria.radar { return false }
            if let start = Self.compactCatalogDate(criteria.startDate), item.date < start { return false }
            if let end = Self.compactCatalogDate(criteria.endDate), item.date > end { return false }
            return true
        }
        let pulses = matchingItems.flatMap { item in
            item.pulses + item.quantityRecords.map(\.pulse) + item.rawVolumes.map(\.pulse)
        }
        return Array(Set(pulses.filter { !$0.isEmpty })).sorted()
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
            if let start, item.date < start { return false }
            if let end, item.date > end { return false }
            if !criteria.pulse.isEmpty && !item.matchesPulse(criteria.pulse) { return false }
            guard !tokens.isEmpty else { return true }
            let haystack = item.searchText.lowercased()
            return tokens.allSatisfy { haystack.contains($0) }
        }
        .sorted {
            ($0.date, $0.radarDisplayName, $0.radarNum) > ($1.date, $1.radarDisplayName, $1.radarNum)
        }
    }

    var catalogSearchSummary: String {
        let count = filteredCatalogItems.count
        guard !catalog.isEmpty else { return "No catalog" }
        if count == catalog.count {
            return "\(count) item\(count == 1 ? "" : "s")"
        }
        return "\(count) of \(catalog.count) item\(catalog.count == 1 ? "" : "s")"
    }

    var catalogDateRange: (start: String, end: String)? {
        let dates = catalog.map(\.date).filter { !$0.isEmpty }.sorted()
        guard let start = dates.first, let end = dates.last else { return nil }
        return (start, end)
    }

    func radarDisplayName(_ radar: String) -> String {
        catalog.first { $0.radar == radar }?.radarDisplayName ?? radar
    }

    var availablePulses: [String] {
        guard let item = selectedItem else { return [] }
        let fromRecords = Set(item.quantityRecords.map(\.pulse).filter { !$0.isEmpty })
        return Array(fromRecords.isEmpty ? Set(item.pulses) : fromRecords).sorted()
    }

    var availableTimes: [String] {
        guard let item = selectedItem else { return [] }
        let fromRecords = item.quantityRecords
            .filter { selectedPulse.isEmpty || $0.pulse == selectedPulse }
            .map(\.time)
            .filter { !$0.isEmpty }
        return Array(Set(fromRecords.isEmpty ? item.times : fromRecords)).sorted()
    }

    var availableQuantities: [String] {
        guard let item = selectedItem else { return [] }
        let fromRecords = item.quantityRecords
            .filter { selectedPulse.isEmpty || $0.pulse == selectedPulse }
            .filter { selectedTime.isEmpty || $0.time == selectedTime }
            .map(\.quantity)
            .filter { !$0.isEmpty }
        return Array(Set(fromRecords.isEmpty ? item.quantities : fromRecords)).sorted()
    }

    var availableDatasets: [QuantityRecord] {
        guard let item = selectedItem else { return [] }
        let records = item.quantityRecords
            .filter { selectedPulse.isEmpty || $0.pulse == selectedPulse }
            .filter { selectedTime.isEmpty || $0.time == selectedTime }
            .filter { selectedQuantity.isEmpty || $0.quantity == selectedQuantity }
        return records.sorted {
            (($0.nominalHeightM ?? Double.greatestFiniteMagnitude), $0.dataset) <
                (($1.nominalHeightM ?? Double.greatestFiniteMagnitude), $1.dataset)
        }
    }

    var selectedFieldSummary: String {
        [selectedPulse, selectedTime, selectedQuantity, selectedDataset.isEmpty ? "auto" : "dataset\(selectedDataset)"]
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }

    var selectedSourceSizeText: String {
        guard let item = selectedItem else { return "" }
        if item.sourceType == "raw_volume_day" {
            if let volume = item.rawVolume(for: selectedPulse, time: selectedTime) {
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

        if let frame {
            rows.append(SourceDiagnosticRow(label: "Decoded", value: "\(frame.sourceShape.first ?? 0)x\(frame.sourceShape.dropFirst().first ?? 0)"))
            rows.append(SourceDiagnosticRow(label: "Rendered", value: "\(frame.rows)x\(frame.columns), \(frame.palette)"))
            if let min = frame.stats.scaleMin, let max = frame.stats.scaleMax {
                rows.append(SourceDiagnosticRow(label: "Display", value: String(format: "%.2f to %.2f", min, max)))
            }
            if frame.noiseFloor.enabled {
                rows.append(SourceDiagnosticRow(label: "Noise floor", value: "\(frame.noiseFloor.maskedCount) masked"))
            }
        }

        return rows
    }

    func loadCatalog() async {
        isLoadingCatalog = true
        warningMessage = nil
        defer { isLoadingCatalog = false }
        do {
            _ = try? cache.prune()
            cacheStatus = cache.status()
            catalog = try await catalogService.fetchCatalog()
            let launchDefaultSelection = await applyLaunchDefaultSelectionIfNeeded()
            if selectedItemID == nil {
                selectedItemID = latestCatalogItem()?.id ?? catalog.first?.id
            }
            normalizeSelection(preferLatestTime: launchDefaultSelection != nil)
            await hydrateSelectedItemIfNeeded()
            if launchDefaultSelection != nil {
                normalizeSelection(resetDataset: true, preferLatestTime: true)
            }
            statusMessage = launchDefaultSelection?.statusText ?? (catalog.isEmpty ? "Catalog loaded but contained no items." : "Loaded \(catalog.count) catalog item\(catalog.count == 1 ? "" : "s").")
            await renderCurrent()
        } catch {
            statusMessage = "Catalog load failed."
            warningMessage = error.localizedDescription
        }
    }

    func itemSelectionChanged() {
        normalizeSelection(resetDataset: true)
        Task {
            await hydrateSelectedItemIfNeeded()
            await renderCurrent()
        }
    }

    func fieldSelectionChanged(resetDataset: Bool = false) {
        normalizeSelection(resetDataset: resetDataset)
        Task { await renderCurrent() }
    }

    func stepTime(by delta: Int) {
        let times = availableTimes
        guard !times.isEmpty else { return }
        let currentIndex = times.firstIndex(of: selectedTime) ?? 0
        let nextIndex = (currentIndex + delta + times.count) % times.count
        selectedTime = times[nextIndex]
        fieldSelectionChanged(resetDataset: true)
    }

    func selectCatalogItem(_ item: CatalogItem) {
        selectedItemID = item.id
        itemSelectionChanged()
    }

    func resetCatalogSearch() {
        catalogSearch = CatalogSearchCriteria()
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

    func filtersChanged() {
        Task { await renderCurrent() }
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
            await renderCurrent()
        } catch {
            statusMessage = "Download failed."
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
        guard let item = selectedItem else { return }
        normalizeSelection()
        guard !selectedPulse.isEmpty, !selectedTime.isEmpty, !selectedQuantity.isEmpty else {
            frame = nil
            return
        }

        isRendering = true
        defer { isRendering = false }

        let selection = FieldSelection(
            pulse: selectedPulse,
            time: selectedTime,
            quantity: selectedQuantity,
            dataset: selectedDataset.isEmpty ? nil : selectedDataset,
            cappiHeightM: filters.cappiHeightM
        )

        let field: PolarField
        let localURL: URL
        do {
            localURL = try await cachedOrDownloadSource(for: item, selection: selection)
        } catch {
            frame = nil
            warningMessage = error.localizedDescription
            statusMessage = "Unable to cache source for \(item.title) \(selectedFieldSummary)."
            return
        }
        guard requestID == renderRequestID else { return }

        do {
            field = try hdf5Reader.readPolarField(from: localURL, item: item, selection: selection)
            warningMessage = nil
        } catch {
            frame = nil
            warningMessage = error.localizedDescription
            statusMessage = "Unable to render \(item.title) \(selectedFieldSummary)."
            return
        }
        guard requestID == renderRequestID else { return }
        frame = renderer.render(field: field, filters: filters)
        identifyResult = nil
        cacheStatus = cache.status()
        statusMessage = "Rendered \(item.title) \(selectedFieldSummary)."
    }

    func identify(row: Int, column: Int) {
        guard let frame else { return }
        identifyResult = renderer.identify(frame: frame, row: row, column: column)
    }

    private func applyLaunchDefaultSelectionIfNeeded() async -> LaunchDefaultSelection? {
        guard !hasAppliedLaunchDefaultSelection else { return nil }
        hasAppliedLaunchDefaultSelection = true
        guard selectedItemID == nil, !catalog.isEmpty else { return nil }

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

    private func latestCatalogItem(forRadar radar: String? = nil) -> CatalogItem? {
        catalog
            .filter { radar == nil || $0.radar == radar }
            .max { lhs, rhs in
                if lhs.date != rhs.date { return lhs.date < rhs.date }
                if lhs.modifiedTime != rhs.modifiedTime { return lhs.modifiedTime < rhs.modifiedTime }
                return lhs.id < rhs.id
            }
    }

    private func cachedOrDownloadSource(for item: CatalogItem, selection: FieldSelection) async throws -> URL {
        if let localURL = cache.existingSourceURL(for: item, pulse: selection.pulse, time: selection.time) {
            return localURL
        }

        isDownloading = true
        warningMessage = nil
        statusMessage = "Downloading raw HDF5 for \(item.title) \(selectedFieldSummary)..."
        defer {
            isDownloading = false
            cacheStatus = cache.status()
        }

        let localURL = try await cache.downloadSelectedSource(for: item, pulse: selection.pulse, time: selection.time)
        statusMessage = "Cached \(localURL.lastPathComponent)."
        return localURL
    }

    private var selectedDatasetSummary: String {
        if let record = availableDatasets.first(where: { $0.dataset == selectedDataset }) {
            if let elevation = record.elevationDeg {
                return "\(String(format: "%.2f", elevation)) deg (\(record.datasetName))"
            }
            if let height = record.nominalHeightM {
                return "\(Int(height)) m (\(record.datasetName))"
            }
            return record.datasetName
        }
        return selectedDataset.isEmpty ? "Auto" : "dataset\(selectedDataset)"
    }

    private var selectedCacheStatusText: String {
        guard let item = selectedItem else { return "No item" }
        guard let url = cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) else {
            return "Not cached"
        }
        return "Cached \(url.lastPathComponent)"
    }

    private func selectedSourceURL(for item: CatalogItem) -> URL? {
        if item.sourceType == "raw_volume_day", let volume = item.rawVolume(for: selectedPulse, time: selectedTime) {
            return volume.downloadURL(publicBaseURL: AppConfiguration.publicBaseURL)
        }
        return item.aggregateURL(publicBaseURL: AppConfiguration.publicBaseURL)
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

    private func normalizeSelection(resetDataset: Bool = false, preferLatestTime: Bool = false) {
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
        if resetDataset || !availableDatasets.contains(where: { $0.dataset == selectedDataset }) {
            selectedDataset = availableDatasets.first?.dataset ?? ""
        }
        filters.cappiHeightM = filters.cappiHeightM
    }

    private func hydrateSelectedItemIfNeeded() async {
        guard let item = selectedItem else { return }
        guard item.sourceType == "raw_volume_day", item.rawVolumes.isEmpty else { return }
        do {
            statusMessage = "Loading scan catalog for \(item.title)..."
            let rawItems = try await catalogService.fetchRawVolumeCatalog(for: item)
            guard !rawItems.isEmpty else { return }
            let hydrated = item.hydrated(with: rawItems)
            if let index = catalog.firstIndex(where: { $0.id == item.id }) {
                catalog[index] = hydrated
            }
            normalizeSelection(resetDataset: true)
        } catch {
            warningMessage = "Raw-volume catalog load failed: \(error.localizedDescription)"
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
        ] + pulses + quantities + quantityRecords.map(\.quantity) + quantityRecords.map(\.pulse))
            .joined(separator: " ")
    }

    func matchesPulse(_ pulse: String) -> Bool {
        pulses.contains(pulse) ||
            quantityRecords.contains { $0.pulse == pulse } ||
            rawVolumes.contains { $0.pulse == pulse }
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
