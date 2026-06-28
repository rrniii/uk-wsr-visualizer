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

    func prune(maxAge: TimeInterval = AppConfiguration.cacheTTLSeconds, maxBytes: Int64 = AppConfiguration.maxCacheBytes) throws {
        guard let enumerator = fileManager.enumerator(
            at: rootDirectory,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]
        ) else { return }

        var files = [(url: URL, size: Int64, modified: Date)]()
        for case let file as URL in enumerator {
            let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey])
            guard values?.isRegularFile == true else { continue }
            let size = Int64(values?.fileSize ?? 0)
            let modified = values?.contentModificationDate ?? .distantPast
            files.append((file, size, modified))
        }

        let now = Date()
        for file in files where maxAge >= 0 && now.timeIntervalSince(file.modified) > maxAge {
            try? fileManager.removeItem(at: file.url)
        }

        files = files.filter { fileManager.fileExists(atPath: $0.url.path) }
        var totalBytes = files.reduce(Int64(0)) { $0 + $1.size }
        for file in files.sorted(by: { $0.modified < $1.modified }) where maxBytes >= 0 && totalBytes > maxBytes {
            try? fileManager.removeItem(at: file.url)
            totalBytes -= file.size
        }
    }

    func downloadSelectedSource(for item: CatalogItem, pulse: String, time: String, publicBaseURL: URL = AppConfiguration.publicBaseURL) async throws -> URL {
        if item.sourceType == "raw_volume_day", let volume = item.rawVolume(for: pulse, time: time) {
            return try await downloadVolume(volume, for: item, publicBaseURL: publicBaseURL)
        }
        return try await downloadAggregate(for: item, publicBaseURL: publicBaseURL)
    }

    private func downloadAggregate(for item: CatalogItem, publicBaseURL: URL) async throws -> URL {
        try prune()
        guard let remoteURL = item.aggregateURL(publicBaseURL: publicBaseURL) else {
            throw RadarAppError.noAggregateURL(item.title)
        }

        let destination = localAggregateURL(for: item)
        return try await download(remoteURL: remoteURL, destination: destination, expectedSize: item.fileSize)
    }

    private func downloadVolume(_ volume: RawVolumeRecord, for item: CatalogItem, publicBaseURL: URL) async throws -> URL {
        try prune()
        guard let remoteURL = volume.downloadURL(publicBaseURL: publicBaseURL) else {
            throw RadarAppError.noAggregateURL("\(item.title) \(volume.pulse) \(volume.time)")
        }

        let destination = localVolumeURL(for: item, volume: volume)
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
                throw URLError(.cannotDecodeRawData)
            }
        }
        try? fileManager.removeItem(at: destination)
        try fileManager.moveItem(at: temporaryURL, to: destination)
        try prune()
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

    private let catalogService: CatalogService
    private let cache: RadarCache
    private let hdf5Reader: RadarVolumeReader
    private let renderer = RadarRenderer()

    init(
        catalogService: CatalogService = CatalogService(),
        cache: RadarCache = .live,
        hdf5Reader: RadarVolumeReader = NativeHDF5VolumeReader()
    ) {
        self.catalogService = catalogService
        self.cache = cache
        self.hdf5Reader = hdf5Reader
        self.cacheStatus = cache.status()
    }

    var selectedItem: CatalogItem? {
        guard let selectedItemID else { return nil }
        return catalog.first { $0.id == selectedItemID }
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

    func loadCatalog() async {
        isLoadingCatalog = true
        warningMessage = nil
        defer { isLoadingCatalog = false }
        do {
            catalog = try await catalogService.fetchCatalog()
            selectedItemID = selectedItemID ?? catalog.first?.id
            normalizeSelection()
            await hydrateSelectedItemIfNeeded()
            statusMessage = catalog.isEmpty ? "Catalog loaded but contained no items." : "Loaded \(catalog.count) catalog item\(catalog.count == 1 ? "" : "s")."
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
            statusMessage = "Raw cache cleared."
        } catch {
            warningMessage = error.localizedDescription
        }
    }

    func renderCurrent() async {
        guard selectedItem != nil else { return }
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
        if let localURL = cache.existingSourceURL(for: item, pulse: selectedPulse, time: selectedTime) {
            do {
                field = try hdf5Reader.readPolarField(from: localURL, item: item, selection: selection)
                warningMessage = nil
            } catch {
                frame = nil
                warningMessage = error.localizedDescription
                statusMessage = "Unable to render \(item.title) \(selectedFieldSummary)."
                return
            }
        } else {
            frame = nil
            warningMessage = "Cache the selected HDF5 scan before rendering. Synthetic radar data is disabled."
            statusMessage = "Waiting for source data for \(item.title) \(selectedFieldSummary)."
            return
        }
        frame = renderer.render(field: field, filters: filters)
        identifyResult = nil
        statusMessage = "Rendered \(item.title) \(selectedFieldSummary)."
    }

    func identify(row: Int, column: Int) {
        guard let frame else { return }
        identifyResult = renderer.identify(frame: frame, row: row, column: column)
    }

    private func normalizeSelection(resetDataset: Bool = false) {
        guard selectedItem != nil else { return }
        if !availablePulses.contains(selectedPulse) {
            selectedPulse = availablePulses.first ?? ""
        }
        if !availableTimes.contains(selectedTime) {
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
}
