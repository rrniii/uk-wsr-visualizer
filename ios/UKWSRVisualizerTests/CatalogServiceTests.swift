import CoreLocation
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
