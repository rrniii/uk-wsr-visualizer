import CoreLocation
import UIKit
import XCTest
@testable import UKWSRVisualizer

private actor FixtureResponses {
    private var responses: [String: Data]
    private var requestedURLs: [String] = []

    init(_ responses: [String: String]) {
        self.responses = responses.mapValues { Data($0.utf8) }
    }

    func data(for url: URL) throws -> Data {
        let key = url.absoluteString
        requestedURLs.append(key)
        guard let data = responses[key] else {
            throw URLError(.fileDoesNotExist)
        }
        return data
    }

    func requests() -> [String] {
        requestedURLs
    }
}

@MainActor
private final class FixedLocationProvider: DeviceLocationProviding {
    var location: CLLocation?

    init(location: CLLocation?) {
        self.location = location
    }

    func requestCurrentLocation(timeout: TimeInterval) async -> CLLocation? {
        location
    }
}

private struct UnexpectedVolumeReader: RadarVolumeReader {
    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        throw RadarAppError.unsupportedFixture("Unexpected HDF5 read in unit test")
    }
}

private final class CapturedFieldSelections {
    var selections: [FieldSelection] = []
}

private struct InspectingVolumeReader: RadarVolumeReader {
    var recordsByTime: [String: [QuantityRecord]]
    var capture: CapturedFieldSelections

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        recordsByTime[time] ?? []
    }

    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        capture.selections.append(selection)
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: selection.quantity,
            dataset: selection.dataset ?? "",
            latitude: 54.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 2.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 2
        )
        return PolarField(values: [1, 2, 3, 4], rows: 2, columns: 2, metadata: metadata)
    }
}

private final class MemoryRecentSelectionStore: RecentSelectionStoring {
    var selections: [RecentCatalogSelection]

    init(_ selections: [RecentCatalogSelection] = []) {
        self.selections = selections
    }

    func loadRecentSelections() -> [RecentCatalogSelection] {
        selections
    }

    func saveRecentSelections(_ selections: [RecentCatalogSelection]) {
        self.selections = selections
    }
}

final class CatalogServiceTests: XCTestCase {
    private let rootURL = URL(string: "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/catalog.json")!
    private let baseURL = URL(string: "https://fixtures.invalid")!

    func testInterimPVOLRootDecodesSpatialAndLoadsOnlyLatestCoverageAtStartup() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.interimRootJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json": Self.castor2026CoverageJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json": Self.chenies2026CoverageJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }

        let items = try await service.fetchCatalog()
        let requests = await fixtures.requests()

        XCTAssertEqual(items.map(\.radar), ["castor-bay", "chenies"])
        XCTAssertEqual(items.first(where: { $0.radar == "chenies" })?.spatialMetadata?.latitude, 51.68944444444444)
        XCTAssertEqual(items.first(where: { $0.radar == "chenies" })?.spatialMetadata?.heightM, 153)
        XCTAssertEqual(items.first(where: { $0.radar == "castor-bay" })?.date, "20260621")
        XCTAssertTrue(requests.contains(rootURL.absoluteString))
        XCTAssertTrue(requests.contains("https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json"))
        XCTAssertTrue(requests.contains("https://fixtures.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json"))
        XCTAssertFalse(requests.contains("https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json"))
        XCTAssertFalse(requests.contains { $0.contains("/2026/06/21/catalog.json") })
    }

    func testPublishedPVOLRootWithoutInterimFlagsLoadsLatestCoverageAtStartup() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.withoutInterimFlags(Self.interimRootJSON),
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json": Self.withoutInterimFlags(Self.castor2026CoverageJSON),
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json": Self.withoutInterimFlags(Self.chenies2026CoverageJSON),
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }

        let items = try await service.fetchCatalog()

        XCTAssertEqual(items.map(\.radar), ["castor-bay", "chenies"])
        XCTAssertEqual(items.first(where: { $0.radar == "castor-bay" })?.validationStatus, "published")
        XCTAssertEqual(items.first(where: { $0.radar == "castor-bay" })?.rootAttrs["interim"], "false")
        XCTAssertEqual(items.first(where: { $0.radar == "castor-bay" })?.rootAttrs["upload_complete"], "true")
    }

    func testFetchCoverageDaysLoadsRequestedYearAndCarriesRootSpatialMetadata() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.interimRootJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json": Self.castor2025CoverageJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }

        let items = try await service.fetchCoverageDays(forRadar: "castor-bay", years: ["2025"])
        let requests = await fixtures.requests()

        XCTAssertEqual(items.map(\.date), ["20250115"])
        XCTAssertEqual(items.first?.rawVolumeCatalogKey, "ukmo-nimrod/catalog/pvol/castor-bay/2025/01/15/catalog.json")
        XCTAssertEqual(items.first?.spatialMetadata?.longitude, -6.342777777777777)
        XCTAssertEqual(requests, [
            rootURL.absoluteString,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json",
        ])
    }

    @MainActor
    func testCatalogSearchUsesRootYearAvailabilityBeforeCoverageIsLoaded() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.interimRootJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json": Self.castor2026CoverageJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json": Self.chenies2026CoverageJSON,
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json": Self.castor2025CoverageJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }
        let cacheRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: cacheRoot) }
        let model = VisualizerViewModel(
            catalogService: service,
            cache: RadarCache(rootDirectory: cacheRoot),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )

        await model.loadCatalog()
        model.catalogSearch.radar = "castor-bay"

        XCTAssertEqual(model.catalogYearOptions, ["2026", "2025"])
        XCTAssertEqual(model.catalogDateRange?.start, "20250115")
        XCTAssertEqual(model.catalogDateRange?.end, "20260621")
        XCTAssertEqual(model.filteredCatalogItems.map(\.date), ["20260621"])

        model.catalogSearch.year = "2025"
        await model.loadCoverageForCurrentSearch()

        XCTAssertTrue(model.filteredCatalogItems.contains { $0.date == "20250115" })
        let requests = await fixtures.requests()
        XCTAssertTrue(requests.contains("https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json"))
    }

    func testDayCatalogHydratesRawVolumeFilesWithObjectURLsAndSizes() async throws {
        let day = try XCTUnwrap(try JSONDecoder().decode(InterimPVOLCoverage.self, from: Data(Self.castor2026CoverageJSON.utf8)).days.first)
        let root = try JSONDecoder().decode(InterimPVOLRootCatalog.self, from: Data(Self.interimRootJSON.utf8))
        let radar = try XCTUnwrap(root.radars.first { $0.radar == "castor-bay" })
        let item = CatalogItem(interimPVOLDay: day, radar: radar, root: root)
        let fixtures = FixtureResponses([
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json": Self.castorDayCatalogJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }

        let rawItems = try await service.fetchRawVolumeCatalog(for: item)

        XCTAssertEqual(rawItems.count, 2)
        XCTAssertEqual(rawItems.first?.objectURL, "https://fixtures.invalid/ukmo-nimrod/pvol/castor-bay/2026/06/21/lp/castor-lp-1445.h5")
        XCTAssertEqual(rawItems.first?.fileSize, 3_109_818)
        XCTAssertEqual(rawItems.first?.timesByPulse["lp"], ["1445"])
        XCTAssertEqual(rawItems.first?.quantities, [])
    }

    func testPublishedDayCatalogWithoutInterimFlagsHydratesRawVolumeFiles() async throws {
        let day = try XCTUnwrap(try JSONDecoder().decode(InterimPVOLCoverage.self, from: Data(Self.withoutInterimFlags(Self.castor2026CoverageJSON).utf8)).days.first)
        let root = try JSONDecoder().decode(InterimPVOLRootCatalog.self, from: Data(Self.withoutInterimFlags(Self.interimRootJSON).utf8))
        let radar = try XCTUnwrap(root.radars.first { $0.radar == "castor-bay" })
        let item = CatalogItem(interimPVOLDay: day, radar: radar, root: root)
        let fixtures = FixtureResponses([
            "https://fixtures.invalid/ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json": Self.withoutInterimFlags(Self.castorDayCatalogJSON),
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }

        let rawItems = try await service.fetchRawVolumeCatalog(for: item)

        XCTAssertEqual(rawItems.count, 2)
        XCTAssertEqual(rawItems.first?.validationStatus, "published")
        XCTAssertEqual(rawItems.first?.rootAttrs["interim"], "false")
        XCTAssertEqual(rawItems.first?.rootAttrs["upload_complete"], "true")
    }

    @MainActor
    func testLaunchDefaultSelectsNearestRadarFromSpatialMetadata() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.legacyEnvelopeJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }
        let model = VisualizerViewModel(
            catalogService: service,
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: CLLocation(latitude: 51.7, longitude: -0.5))
        )

        await model.loadCatalog()

        XCTAssertEqual(model.selectedItem?.radar, "chenies")
        XCTAssertEqual(model.frame, nil)
        XCTAssertTrue(model.statusMessage.contains("No pulse"))
    }

    @MainActor
    func testSelectingNewItemClearsStaleWarningImmediately() {
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        let first = CatalogItem(radar: "chenies", date: "20260622")
        let second = CatalogItem(radar: "castor-bay", date: "20260621")
        model.catalog = [first, second]
        model.selectedItemID = first.id
        model.warningMessage = "Stale Chenies error"

        model.selectCatalogItem(second)

        XCTAssertEqual(model.selectedItemID, second.id)
        XCTAssertNil(model.warningMessage)
        XCTAssertEqual(model.frame, nil)
    }

    @MainActor
    func testCatalogSearchFiltersCachedRenderableQuantityAndSorts() throws {
        let cacheRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: cacheRoot) }
        let cache = RadarCache(rootDirectory: cacheRoot)
        let volume = RawVolumeRecord(
            pulse: "lp",
            time: "1445",
            path: "",
            filename: "castor-lp-1445.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/castor-bay/2026/06/22/lp/castor-lp-1445.h5",
            objectURL: "https://fixtures.invalid/castor-lp-1445.h5",
            quantities: ["DBZH"]
        )
        let cached = CatalogItem(
            radar: "castor-bay",
            radarNum: "07",
            date: "20260622",
            fileSize: 4,
            modifiedTime: 10,
            pulses: ["lp"],
            quantities: ["DBZH"],
            sourceType: "raw_volume_day",
            rawVolumes: [volume],
            validationStatus: "interim"
        )
        let unavailable = CatalogItem(
            radar: "chenies",
            radarNum: "05",
            date: "20260623",
            sourceType: "raw_volume_day",
            validationStatus: "unknown"
        )
        let localURL = cache.localVolumeURL(for: cached, volume: volume)
        try FileManager.default.createDirectory(at: localURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("HDF5".utf8).write(to: localURL)

        let model = VisualizerViewModel(
            cache: cache,
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [unavailable, cached]
        model.catalogSearch.quantity = "DBZH"
        model.catalogSearch.renderableOnly = true
        model.catalogSearch.cachedOnly = true
        model.catalogSearch.sortMode = .cachedFirst

        XCTAssertEqual(model.filteredCatalogItems.map(\.id), [cached.id])
        XCTAssertEqual(model.catalogQuantityOptions, ["DBZH"])
        XCTAssertTrue(model.catalogRowBadges(for: cached).contains("Cached"))
        XCTAssertTrue(model.catalogRowBadges(for: cached).contains("Renderable"))
        XCTAssertTrue(model.catalogRowBadges(for: unavailable).contains("No source"))
    }

    @MainActor
    func testInspectedMetadataDoesNotCollapseAvailableTimes() throws {
        let volume1445 = RawVolumeRecord(
            pulse: "lp",
            time: "1445",
            path: "",
            filename: "castor-lp-1445.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/castor-bay/2026/06/22/lp/castor-lp-1445.h5",
            objectURL: "https://fixtures.invalid/castor-lp-1445.h5",
            quantities: ["DBZH"]
        )
        let volume1450 = RawVolumeRecord(
            pulse: "lp",
            time: "1450",
            path: "",
            filename: "castor-lp-1450.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/castor-bay/2026/06/22/lp/castor-lp-1450.h5",
            objectURL: "https://fixtures.invalid/castor-lp-1450.h5",
            quantities: []
        )
        let item = CatalogItem(
            radar: "castor-bay",
            date: "20260622",
            pulses: ["lp"],
            times: ["1445", "1450"],
            quantities: ["DBZH"],
            quantityRecords: [
                QuantityRecord(pulse: "lp", time: "1445", dataset: "1", kind: "data", index: "1", quantity: "DBZH")
            ],
            sourceType: "raw_volume_day",
            rawVolumes: [volume1445, volume1450],
            timesByPulse: ["lp": ["1445", "1450"]]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id
        model.selectedPulse = "lp"
        model.selectedTime = "1445"

        XCTAssertEqual(model.availableTimes, ["1445", "1450"])
        XCTAssertEqual(model.availableQuantities, ["DBZH"])

        model.selectedTime = "1450"

        XCTAssertEqual(model.availableTimes, ["1445", "1450"])
        XCTAssertEqual(model.availableQuantities, [])
        XCTAssertTrue(model.canAutoSelectFileQuantity)
    }

    @MainActor
    func testChangingTimePreservesSelectedElevationWhenAvailable() throws {
        let volume0000 = RawVolumeRecord(
            pulse: "sp",
            time: "0000",
            path: "",
            filename: "hameldon-sp-0000.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/sp/hameldon-sp-0000.h5",
            objectURL: "https://fixtures.invalid/hameldon-sp-0000.h5",
            quantities: ["DBZH"]
        )
        let volume0010 = RawVolumeRecord(
            pulse: "sp",
            time: "0010",
            path: "",
            filename: "hameldon-sp-0010.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/sp/hameldon-sp-0010.h5",
            objectURL: "https://fixtures.invalid/hameldon-sp-0010.h5",
            quantities: ["DBZH"]
        )
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260622",
            pulses: ["sp"],
            times: ["0000", "0010"],
            quantities: ["DBZH"],
            quantityRecords: [
                QuantityRecord(pulse: "sp", time: "0000", dataset: "dataset1", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0000", dataset: "dataset2", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0),
                QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-a", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-b", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0)
            ],
            sourceType: "raw_volume_day",
            rawVolumes: [volume0000, volume0010],
            timesByPulse: ["sp": ["0000", "0010"]]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id
        model.selectedPulse = "sp"
        model.selectedTime = "0000"
        model.selectedQuantity = "DBZH"
        model.selectedDataset = "dataset2"

        XCTAssertEqual(model.selectedElevationText, "2.00°")

        model.selectTime("0010")

        XCTAssertEqual(model.selectedTime, "0010")
        XCTAssertEqual(model.selectedDataset, "scan-b")
        XCTAssertEqual(model.selectedElevationText, "2.00°")
    }

    @MainActor
    func testChangingTimePreservesSelectedElevationAfterMetadataInspection() async throws {
        let volume0000 = RawVolumeRecord(
            pulse: "sp",
            time: "0000",
            path: "",
            filename: "hameldon-sp-0000.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/sp/hameldon-sp-0000.h5",
            objectURL: "https://fixtures.invalid/hameldon-sp-0000.h5",
            quantities: ["DBZH"]
        )
        let volume0010 = RawVolumeRecord(
            pulse: "sp",
            time: "0010",
            path: "",
            filename: "hameldon-sp-0010.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/sp/hameldon-sp-0010.h5",
            objectURL: "https://fixtures.invalid/hameldon-sp-0010.h5",
            quantities: ["DBZH"]
        )
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260622",
            pulses: ["sp"],
            times: ["0000", "0010"],
            quantities: ["DBZH"],
            quantityRecords: [
                QuantityRecord(pulse: "sp", time: "0000", dataset: "dataset1", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0000", dataset: "dataset2", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0)
            ],
            sourceType: "raw_volume_day",
            rawVolumes: [volume0000, volume0010],
            timesByPulse: ["sp": ["0000", "0010"]]
        )
        let rootDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let cache = RadarCache(rootDirectory: rootDirectory)
        let cachedURL = cache.localVolumeURL(for: item, volume: volume0010)
        try FileManager.default.createDirectory(at: cachedURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("test".utf8).write(to: cachedURL)

        let capture = CapturedFieldSelections()
        let model = VisualizerViewModel(
            cache: cache,
            hdf5Reader: InspectingVolumeReader(
                recordsByTime: [
                    "0010": [
                        QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-a", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                        QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-b", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0)
                    ]
                ],
                capture: capture
            ),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id
        model.selectedPulse = "sp"
        model.selectedTime = "0000"
        model.selectedQuantity = "DBZH"
        model.selectedDataset = "dataset2"

        model.selectTime("0010")

        XCTAssertEqual(model.selectedTime, "0010")
        XCTAssertEqual(model.selectedDataset, "dataset2")

        await model.renderCurrent()

        XCTAssertEqual(model.selectedDataset, "scan-b")
        XCTAssertEqual(model.selectedElevationText, "2.00°")
        XCTAssertEqual(capture.selections.last?.dataset, "scan-b")
    }

    @MainActor
    func testChangingQuantityPreservesOtherCompatibleSelections() throws {
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260622",
            pulses: ["lp"],
            times: ["0050"],
            quantities: ["DBZH", "VRADH"],
            quantityRecords: [
                QuantityRecord(pulse: "lp", time: "0050", dataset: "dbzh-1", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "lp", time: "0050", dataset: "dbzh-2", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0),
                QuantityRecord(pulse: "lp", time: "0050", dataset: "vradh-1", kind: "data", index: "3", quantity: "VRADH", elevationDeg: 1.0),
                QuantityRecord(pulse: "lp", time: "0050", dataset: "vradh-2", kind: "data", index: "4", quantity: "VRADH", elevationDeg: 2.0)
            ]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id
        model.selectedPulse = "lp"
        model.selectedTime = "0050"
        model.selectedQuantity = "DBZH"
        model.selectedDataset = "dbzh-2"

        model.selectQuantity("VRADH")

        XCTAssertEqual(model.selectedPulse, "lp")
        XCTAssertEqual(model.selectedTime, "0050")
        XCTAssertEqual(model.selectedQuantity, "VRADH")
        XCTAssertEqual(model.selectedDataset, "vradh-2")
        XCTAssertEqual(model.selectedElevationText, "2.00°")
    }

    @MainActor
    func testChangingPulsePreservesOtherCompatibleSelections() throws {
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260622",
            pulses: ["lp", "sp"],
            times: ["0050"],
            quantities: ["DBZH"],
            quantityRecords: [
                QuantityRecord(pulse: "lp", time: "0050", dataset: "lp-1", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "lp", time: "0050", dataset: "lp-2", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0),
                QuantityRecord(pulse: "sp", time: "0050", dataset: "sp-1", kind: "data", index: "3", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0050", dataset: "sp-2", kind: "data", index: "4", quantity: "DBZH", elevationDeg: 2.0)
            ],
            timesByPulse: ["lp": ["0050"], "sp": ["0050"]]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id
        model.selectedPulse = "lp"
        model.selectedTime = "0050"
        model.selectedQuantity = "DBZH"
        model.selectedDataset = "lp-2"

        model.selectPulse("sp")

        XCTAssertEqual(model.selectedPulse, "sp")
        XCTAssertEqual(model.selectedTime, "0050")
        XCTAssertEqual(model.selectedQuantity, "DBZH")
        XCTAssertEqual(model.selectedDataset, "sp-2")
        XCTAssertEqual(model.selectedElevationText, "2.00°")
    }

    @MainActor
    func testTimesAreScopedToSelectedPulseAndDownloadableSource() throws {
        let lp0100 = RawVolumeRecord(
            pulse: "lp",
            time: "0100",
            path: "",
            filename: "hameldon-lp-0100.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/lp/hameldon-lp-0100.h5",
            objectURL: "https://fixtures.invalid/hameldon-lp-0100.h5",
            quantities: ["DBZH"]
        )
        let sp0205WithoutSource = RawVolumeRecord(
            pulse: "sp",
            time: "0205",
            path: "",
            filename: "hameldon-sp-0205.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "",
            objectURL: "",
            quantities: ["DBZH"]
        )
        let sp0300 = RawVolumeRecord(
            pulse: "sp",
            time: "0300",
            path: "",
            filename: "hameldon-sp-0300.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "ukmo-nimrod/pvol/hameldon-hill/2026/06/22/sp/hameldon-sp-0300.h5",
            objectURL: "https://fixtures.invalid/hameldon-sp-0300.h5",
            quantities: ["VRADH"]
        )
        let vp0205WithoutSource = RawVolumeRecord(
            pulse: "vp",
            time: "0205",
            path: "",
            filename: "hameldon-vp-0205.h5",
            fileSize: 4,
            modifiedTime: 10,
            objectKey: "",
            objectURL: "",
            quantities: ["WRADH"]
        )
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260622",
            pulses: ["lp", "sp", "vp"],
            times: ["0100", "0205", "0300"],
            quantities: ["DBZH", "VRADH", "WRADH"],
            quantityRecords: [
                QuantityRecord(pulse: "sp", time: "0205", dataset: "1", kind: "data", index: "1", quantity: "DBZH"),
                QuantityRecord(pulse: "sp", time: "0300", dataset: "1", kind: "data", index: "1", quantity: "VRADH"),
                QuantityRecord(pulse: "vp", time: "0205", dataset: "1", kind: "data", index: "1", quantity: "WRADH")
            ],
            sourceType: "raw_volume_day",
            rawVolumes: [lp0100, sp0205WithoutSource, sp0300, vp0205WithoutSource],
            timesByPulse: [
                "lp": ["0100"],
                "sp": ["0205", "0300"],
                "vp": ["0205"]
            ]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectedItemID = item.id

        model.selectedPulse = "sp"
        model.selectedTime = "0205"

        XCTAssertEqual(model.availablePulses, ["lp", "sp"])
        XCTAssertEqual(model.availableTimes, ["0300"])
        XCTAssertEqual(model.availableQuantities, [])

        model.fieldSelectionChanged(resetDataset: true)

        XCTAssertEqual(model.selectedTime, "0300")
        XCTAssertEqual(model.availableQuantities, ["VRADH"])

        model.selectedPulse = "lp"
        model.fieldSelectionChanged(resetDataset: true)

        XCTAssertEqual(model.availableTimes, ["0100"])
        XCTAssertEqual(model.selectedTime, "0100")
    }

    @MainActor
    func testRecentSelectionPersistsAndRestoresBeforeNearestFallback() async throws {
        let fixtures = FixtureResponses([
            rootURL.absoluteString: Self.legacyEnvelopeJSON,
        ])
        let service = CatalogService(catalogURL: rootURL, publicBaseURL: baseURL) { url in
            try await fixtures.data(for: url)
        }
        let recentItem = CatalogItem(radar: "castor-bay", date: "20260622")
        let store = MemoryRecentSelectionStore([
            RecentCatalogSelection(
                itemID: recentItem.id,
                radar: "castor-bay",
                radarDisplayName: "Castor Bay",
                date: "20260622",
                pulse: "",
                time: "",
                quantity: "",
                dataset: "",
                selectedAt: Date()
            )
        ])
        let model = VisualizerViewModel(
            catalogService: service,
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: CLLocation(latitude: 51.7, longitude: -0.5)),
            recentSelectionStore: store,
            autoRenderEnabled: false
        )

        await model.loadCatalog()

        XCTAssertEqual(model.selectedItem?.radar, "castor-bay")
        XCTAssertTrue(model.statusMessage.contains("Restored"))
    }

    @MainActor
    func testSelectingCatalogItemRecordsRecentSelection() {
        let store = MemoryRecentSelectionStore()
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            recentSelectionStore: store,
            autoRenderEnabled: false
        )
        let item = CatalogItem(radar: "castor-bay", date: "20260621", pulses: ["lp"], times: ["1445"], quantities: ["DBZH"])
        model.catalog = [item]

        model.selectCatalogItem(item)

        XCTAssertEqual(store.selections.first?.itemID, item.id)
        XCTAssertEqual(store.selections.first?.radar, "castor-bay")
    }

    @MainActor
    func testVideoExportPlanKeepsSelectionStableAndSkipsUnavailableTimes() async throws {
        let item = CatalogItem(
            radar: "hameldon-hill",
            date: "20260625",
            pulses: ["sp"],
            times: ["0000", "0010", "0020"],
            quantities: ["DBZH", "VRADH"],
            quantityRecords: [
                QuantityRecord(pulse: "sp", time: "0000", dataset: "d1", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0000", dataset: "d2", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0),
                QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-a", kind: "data", index: "1", quantity: "DBZH", elevationDeg: 1.0),
                QuantityRecord(pulse: "sp", time: "0010", dataset: "scan-b", kind: "data", index: "2", quantity: "DBZH", elevationDeg: 2.0),
                QuantityRecord(pulse: "sp", time: "0020", dataset: "vel", kind: "data", index: "1", quantity: "VRADH", elevationDeg: 2.0),
            ]
        )
        let model = VisualizerViewModel(
            cache: RadarCache(rootDirectory: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)),
            hdf5Reader: UnexpectedVolumeReader(),
            locationProvider: FixedLocationProvider(location: nil),
            autoRenderEnabled: false
        )
        model.catalog = [item]
        model.selectCatalogItem(item)
        model.selectQuantity("DBZH")
        model.selectDataset("d2")
        let originalTime = model.selectedTime
        let originalDataset = model.selectedDataset

        let plan = try await model.makeVideoExportPlan(mode: .fast)

        XCTAssertEqual(plan.mode, .fast)
        XCTAssertEqual(plan.requestedTimes, ["0000", "0010", "0020"])
        XCTAssertEqual(plan.frameRequests.map(\.time), ["0000", "0010"])
        XCTAssertEqual(plan.frameRequests.map { $0.selection.dataset ?? "" }, ["d2", "scan-b"])
        XCTAssertEqual(plan.skippedFrameCount, 1)
        XCTAssertEqual(model.selectedTime, originalTime)
        XCTAssertEqual(model.selectedDataset, originalDataset)
    }

    func testVideoExportFrameStoreResumeStatusCountsSavedFramesOnly() throws {
        let signature = "unit-\(UUID().uuidString)"
        VideoExportFrameStore.clear(signature: signature)
        defer { VideoExportFrameStore.clear(signature: signature) }
        let requestedTimes = ["0000", "0010"]
        let store = try VideoExportFrameStore(
            signature: signature,
            displayName: "Unit Export",
            outputBaseName: "unit-export",
            requestedTimes: requestedTimes
        )
        XCTAssertNil(VideoExportFrameStore.resumeStatus(signature: signature, requestedTimes: requestedTimes))

        let image = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2)).image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 2, height: 2))
        }
        try store.saveFrame(image: image, index: 0, time: "0000")

        let status = try XCTUnwrap(VideoExportFrameStore.resumeStatus(signature: signature, requestedTimes: requestedTimes))
        XCTAssertEqual(status.completed, 1)
        XCTAssertEqual(status.requested, 2)
        XCTAssertEqual(store.completedTimes, ["0000"])
        XCTAssertEqual(store.availableFrameEntries().map(\.time), ["0000"])
    }

    func testNoiseFloorUsesDesktopSmoothThenFillProfile() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "0230",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 4,
            nrays: 3
        )
        let field = PolarField(
            values: [
                10, .nan, 30, 100,
                10, .nan, 30, 100,
                10, .nan, 30, 100,
            ],
            rows: 3,
            columns: 4,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 3

        let frame = RadarRenderer().render(field: field, filters: filters)

        XCTAssertEqual(frame.noiseFloor.method, "estimated")
        XCTAssertEqual(frame.noiseFloor.operation, "mask")
        XCTAssertEqual(frame.noiseFloor.sourceQuantity, "DBZH")
        XCTAssertEqual(frame.noiseFloor.windowBins, 3)
        XCTAssertEqual(frame.noiseFloor.maskedCount, 0)
        XCTAssertEqual(frame.noiseFloor.floorProfile.compactMap { $0 }, [10, 20, 65, 65])
    }

    func testNoiseFloorUsesReflectivityGateForNonReflectivityFields() {
        let metadata = RadarGridMetadata(
            radar: "ingham",
            date: "20231020",
            pulse: "sp",
            time: "0000",
            quantity: "RHOHV",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 4
        )
        let field = PolarField(
            values: [
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
            ],
            gateValues: [
                5, 20,
                5, 20,
                50, 60,
                50, 60,
            ],
            gateQuantity: "DBZH",
            rows: 4,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 4, maxBins: 2)

        XCTAssertEqual(frame.noiseFloor.sourceQuantity, "DBZH")
        XCTAssertEqual(frame.noiseFloor.maskedCount, 4)
        XCTAssertEqual(frame.noiseFloor.finiteAfter, 4)
        XCTAssertEqual(frame.noiseFloor.floorProfile.compactMap { $0 }, [5, 20])
    }

    func testNoiseFloorDoesNotBlankNonReflectivityFieldsWithoutGateSource() {
        let metadata = RadarGridMetadata(
            radar: "ingham",
            date: "20231020",
            pulse: "sp",
            time: "0000",
            quantity: "SQIH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 4
        )
        let field = PolarField(
            values: [
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
            ],
            rows: 4,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 4, maxBins: 2)

        XCTAssertFalse(frame.noiseFloor.enabled)
        XCTAssertEqual(frame.noiseFloor.maskedCount, 0)
        XCTAssertEqual(frame.valid.filter { $0 }.count, 8)
    }

    func testNoiseFloorCombinesCompanionFieldsConservatively() {
        let metadata = RadarGridMetadata(
            radar: "ingham",
            date: "20231020",
            pulse: "sp",
            time: "0000",
            quantity: "RHOHV",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 4
        )
        let dbzh: [Float] = [
            5, 20,
            5, 20,
            5, 20,
            5, 20,
        ]
        let field = PolarField(
            values: [
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
                0.95, 0.95,
            ],
            gateValues: dbzh,
            gateQuantity: "DBZH",
            companionFields: [
                "SQIH": [
                    0.10, 0.95,
                    0.95, 0.95,
                    0.95, 0.95,
                    0.95, 0.95,
                ],
                "RHOHV": [
                    0.95, 0.50,
                    0.95, 0.95,
                    0.95, 0.95,
                    0.95, 0.95,
                ],
            ],
            rows: 4,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 4, maxBins: 2)

        XCTAssertEqual(frame.noiseFloor.sourceQuantity, "DBZH+SQIH+RHOHV")
        XCTAssertEqual(frame.noiseFloor.maskedCount, 1)
        XCTAssertEqual(frame.noiseFloor.finiteAfter, 7)
        XCTAssertNil(finiteDouble(frame.filteredValues[0]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[1]))
    }

    func testNoiseCleanupMasksLocalStaticClutterPatch() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "1710",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 4,
            nrays: 4
        )
        let dbzh: [Float] = [
            0, 0, 0, 0,
            0, 35, 36, 0,
            0, 34, 38, 0,
            0, 50, 52, 0,
        ]
        let field = PolarField(
            values: dbzh,
            companionFields: [
                "VRADH": [
                    5, 5, 5, 5,
                    5, 0.1, -0.2, 5,
                    5, 0.0, 0.2, 5,
                    5, 4.0, -4.0, 5,
                ],
            ],
            rows: 4,
            columns: 4,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 4, maxBins: 4)

        XCTAssertNil(finiteDouble(frame.filteredValues[5]))
        XCTAssertNil(finiteDouble(frame.filteredValues[6]))
        XCTAssertNil(finiteDouble(frame.filteredValues[9]))
        XCTAssertNil(finiteDouble(frame.filteredValues[10]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[13]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[14]))
    }

    func testLearnedBackgroundModelMasksPersistentClutterGate() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "1710",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 2
        )
        let field = PolarField(
            values: [
                13, -5,
                -5, -5,
            ],
            companionFields: [
                "VRADH": [
                    0.2, 4,
                    4, 4,
                ],
                "SQIH": [
                    0.2, 1,
                    1, 1,
                ],
            ],
            rows: 2,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = false
        filters.backgroundModelEnabled = true
        filters.backgroundMinSamples = 3
        let model = BackgroundModel(
            key: ["radar": "hameldon-hill", "pulse": "sp", "quantity": "DBZH"],
            rows: 2,
            columns: 2,
            sampleCount: [3, 3, 3, 3],
            persistentEchoFrequency: [1, 0, 0, 0],
            dbzhP90: [14, -5, -5, -5],
            nearZeroVradFrequency: [1, 0, 0, 0],
            lowSqiFrequency: [1, 0, 0, 0]
        )

        let frame = RadarRenderer().render(field: field, filters: filters, backgroundModel: model, maxRays: 2, maxBins: 2)

        XCTAssertTrue(frame.backgroundModel.applied)
        XCTAssertEqual(frame.backgroundModel.maskedCount, 1)
        XCTAssertNil(finiteDouble(frame.filteredValues[0]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[1]))
    }

    func testLearnedBackgroundModelPreservesStrongCurrentSignal() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "1710",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 2
        )
        let field = PolarField(
            values: [
                30, -5,
                -5, -5,
            ],
            companionFields: [
                "VRADH": [
                    0.2, 4,
                    4, 4,
                ],
                "SQIH": [
                    0.2, 1,
                    1, 1,
                ],
            ],
            rows: 2,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = false
        filters.backgroundModelEnabled = true
        filters.backgroundMinSamples = 3
        let model = BackgroundModel(
            key: ["radar": "hameldon-hill", "pulse": "sp", "quantity": "DBZH"],
            rows: 2,
            columns: 2,
            sampleCount: [3, 3, 3, 3],
            persistentEchoFrequency: [1, 0, 0, 0],
            dbzhP90: [14, -5, -5, -5],
            nearZeroVradFrequency: [1, 0, 0, 0],
            lowSqiFrequency: [1, 0, 0, 0]
        )

        let frame = RadarRenderer().render(field: field, filters: filters, backgroundModel: model, maxRays: 2, maxBins: 2)

        XCTAssertTrue(frame.backgroundModel.applied)
        XCTAssertEqual(frame.backgroundModel.maskedCount, 0)
        XCTAssertNotNil(finiteDouble(frame.filteredValues[0]))
    }

    func testBackgroundModelDecodesSharedInlineManifest() throws {
        let json = """
        {
          "key": {
            "radar": "hameldon-hill",
            "pulse": "sp",
            "quantity": "DBZH",
            "elevation_deg": 1.0
          },
          "shape": [2, 2],
          "inline_arrays": {
            "sample_count": {
              "dtype": "float32",
              "shape": [2, 2],
              "encoding": "base64",
              "byte_order": "little",
              "data": "AABAQAAAQEAAAEBAAABAQA=="
            },
            "persistent_echo_frequency": {
              "dtype": "float32",
              "shape": [2, 2],
              "encoding": "base64",
              "byte_order": "little",
              "data": "AACAPwAAAAAAAAAAAAAAAA=="
            },
            "dbzh_p90": {
              "dtype": "float32",
              "shape": [2, 2],
              "encoding": "base64",
              "byte_order": "little",
              "data": "AABgQQAAoMAAAKDAAACgwA=="
            }
          }
        }
        """

        let model = try JSONDecoder().decode(BackgroundModel.self, from: Data(json.utf8))

        XCTAssertEqual(model.rows, 2)
        XCTAssertEqual(model.columns, 2)
        XCTAssertEqual(model.key["elevation_deg"], "1")
        XCTAssertEqual(model.sampleCount, [3, 3, 3, 3])
        XCTAssertEqual(model.persistentEchoFrequency, [1, 0, 0, 0])
        XCTAssertEqual(model.dbzhP90, [14, -5, -5, -5])
    }

    func testNoiseCleanupMasksIsolatedReflectivityTextureWithoutNCP() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "1710",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 5,
            nrays: 5
        )
        let dbzh: [Float] = [
            10, 10, 10, 10, 10,
            10, 22, 10, 22, 22,
            10, 10, 10, 22, 22,
            10, 10, 10, 10, 10,
            10, 10, 10, 10, 10,
        ]
        let field = PolarField(
            values: dbzh,
            rows: 5,
            columns: 5,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 5, maxBins: 5)

        XCTAssertNil(finiteDouble(frame.filteredValues[6]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[8]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[9]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[13]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[14]))
    }

    func testNoiseCleanupPreservesStrongMovingLowRhohvSignal() {
        let metadata = RadarGridMetadata(
            radar: "hameldon-hill",
            date: "20260622",
            pulse: "sp",
            time: "1710",
            quantity: "DBZH",
            dataset: "dataset1",
            latitude: 53.0,
            longitude: -2.0,
            heightM: nil,
            elevationDeg: 1.0,
            rstartKm: 0,
            rscaleM: 1,
            nbins: 2,
            nrays: 6
        )
        let dbzh: [Float] = [
            0, 0,
            40, 42,
            50, 52,
            60, 62,
            70, 72,
            80, 82,
        ]
        let field = PolarField(
            values: dbzh,
            companionFields: [
                "VRADH": [
                    4, -4,
                    4, -4,
                    3, -3,
                    3, -3,
                    2.5, -2.5,
                    2, -2,
                ],
                "RHOHV": Array(repeating: Float(0.45), count: 12),
            ],
            rows: 6,
            columns: 2,
            metadata: metadata
        )
        var filters = RadarFilterSet()
        filters.noiseFloorEnabled = true
        filters.noiseFloorMarginDb = 0
        filters.noiseFloorWindowBins = 1

        let frame = RadarRenderer().render(field: field, filters: filters, maxRays: 6, maxBins: 2)

        XCTAssertNotNil(finiteDouble(frame.filteredValues[8]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[9]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[10]))
        XCTAssertNotNil(finiteDouble(frame.filteredValues[11]))
    }

    private static func withoutInterimFlags(_ json: String) -> String {
        json
            .split(separator: "\n", omittingEmptySubsequences: false)
            .filter { !$0.contains("\"interim\"") && !$0.contains("\"upload_complete\"") }
            .joined(separator: "\n")
    }

    private static let interimRootJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T08:42:41Z",
      "interim": true,
      "upload_complete": false,
      "file_count": 42,
      "size_bytes": 1000,
      "radars": [
        {
          "radar": "castor-bay",
          "radar_num": "07",
          "years": ["2025", "2026"],
          "coverage_keys": [
            "ukmo-nimrod/catalog/pvol/castor-bay/2025/coverage.json",
            "ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json"
          ],
          "first_date": "20250115",
          "last_date": "20260621",
          "date_count": 2,
          "file_count": 3,
          "size_bytes": 500,
          "spatial": {
            "latitude": 54.50194444444445,
            "longitude": -6.342777777777777,
            "height_m": 41.0,
            "source": "fixture"
          }
        },
        {
          "radar": "chenies",
          "radar_num": "05",
          "years": ["2026"],
          "coverage_keys": ["ukmo-nimrod/catalog/pvol/chenies/2026/coverage.json"],
          "first_date": "20260622",
          "last_date": "20260622",
          "date_count": 1,
          "file_count": 1,
          "size_bytes": 500,
          "spatial": {
            "latitude": 51.68944444444444,
            "longitude": -0.5302777777777778,
            "height_m": 153.0,
            "source": "fixture"
          }
        }
      ]
    }
    """

    private static let castor2026CoverageJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T08:42:41Z",
      "interim": true,
      "upload_complete": false,
      "radar": "castor-bay",
      "year": "2026",
      "days": [
        {
          "date": "20260621",
          "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json",
          "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/21",
          "file_count": 2,
          "size_bytes": 6200000,
          "pulse_counts": {"lp": 2}
        }
      ]
    }
    """

    private static let castor2025CoverageJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T08:42:41Z",
      "interim": true,
      "upload_complete": false,
      "radar": "castor-bay",
      "year": "2025",
      "days": [
        {
          "date": "20250115",
          "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2025/01/15/catalog.json",
          "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2025/01/15",
          "file_count": 1,
          "size_bytes": 3109818,
          "pulse_counts": {"lp": 1}
        }
      ]
    }
    """

    private static let chenies2026CoverageJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T08:42:41Z",
      "interim": true,
      "upload_complete": false,
      "radar": "chenies",
      "year": "2026",
      "days": [
        {
          "date": "20260622",
          "catalog_key": "ukmo-nimrod/catalog/pvol/chenies/2026/06/22/catalog.json",
          "pvol_prefix": "ukmo-nimrod/pvol/chenies/2026/06/22",
          "file_count": 1,
          "size_bytes": 3109818,
          "pulse_counts": {"lp": 1}
        }
      ]
    }
    """

    private static let castorDayCatalogJSON = """
    {
      "schema_version": 1,
      "generated_at": "2026-06-29T08:42:41Z",
      "interim": true,
      "upload_complete": false,
      "radar": "castor-bay",
      "radar_num": "07",
      "date": "20260621",
      "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json",
      "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/21",
      "file_count": 2,
      "size_bytes": 6200000,
      "pulses": ["lp"],
      "pulse_counts": {"lp": 2},
      "times_by_pulse": {"lp": ["1445", "1450"]},
      "files": [
        {
          "pulse": "lp",
          "time": "1445",
          "filename": "castor-lp-1445.h5",
          "size_bytes": 3109818,
          "modified_time": 1771767531.0657568,
          "object_key": "ukmo-nimrod/pvol/castor-bay/2026/06/21/lp/castor-lp-1445.h5",
          "object_url": "https://fixtures.invalid/ukmo-nimrod/pvol/castor-bay/2026/06/21/lp/castor-lp-1445.h5"
        },
        {
          "pulse": "lp",
          "time": "1450",
          "filename": "castor-lp-1450.h5",
          "size_bytes": 3090182,
          "modified_time": 1771767531.0657568,
          "object_key": "ukmo-nimrod/pvol/castor-bay/2026/06/21/lp/castor-lp-1450.h5",
          "object_url": "https://fixtures.invalid/ukmo-nimrod/pvol/castor-bay/2026/06/21/lp/castor-lp-1450.h5"
        }
      ]
    }
    """

    private static let legacyEnvelopeJSON = """
    {
      "version": 1,
      "items": [
        {
          "radar": "castor-bay",
          "radar_num": "07",
          "date": "20260622",
          "pulses": [],
          "times": [],
          "quantities": [],
          "root_attrs": {
            "uk_wsr:spatial": {
              "latitude": 54.50194444444445,
              "longitude": -6.342777777777777,
              "height_m": 41.0
            }
          }
        },
        {
          "radar": "chenies",
          "radar_num": "05",
          "date": "20260622",
          "pulses": [],
          "times": [],
          "quantities": [],
          "root_attrs": {
            "uk_wsr:spatial": {
              "latitude": 51.68944444444444,
              "longitude": -0.5302777777777778,
              "height_m": 153.0
            }
          }
        }
      ]
    }
    """
}
