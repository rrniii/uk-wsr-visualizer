import CoreLocation
import Foundation
import MapKit
import OSLog
import UIKit

typealias CatalogDataLoader = (URL) async throws -> Data

struct CatalogLoadResult {
    var items: [CatalogItem]
    var pvolRoot: InterimPVOLRootCatalog?
}

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
        try await fetchCatalogLoadResult().items
    }

    func fetchCatalogLoadResult() async throws -> CatalogLoadResult {
        let data = try await fetchData(from: catalogURL)
        let decoder = JSONDecoder()
        let rootDecodeError: Error?
        do {
            let pvolRoot = try decoder.decode(InterimPVOLRootCatalog.self, from: data)
            if !pvolRoot.radars.isEmpty {
                return CatalogLoadResult(
                    items: try await fetchLatestPVOLDays(from: pvolRoot, publicBaseURL: publicBaseURL),
                    pvolRoot: pvolRoot
                )
            }
            rootDecodeError = nil
        } catch {
            rootDecodeError = error
        }
        do {
            let items = try decoder.decode(CatalogEnvelope.self, from: data).items.sorted {
                    ($0.radar, $0.date) < ($1.radar, $1.date)
                }
            return CatalogLoadResult(items: items, pvolRoot: nil)
        } catch {
            let detail = rootDecodeError.map { "PVOL root: \($0.localizedDescription); legacy envelope: \(error.localizedDescription)" } ?? error.localizedDescription
            throw RadarAppError.catalogDecodeFailed(detail)
        }
    }

    func fetchPVOLRootCatalog() async throws -> InterimPVOLRootCatalog {
        try await fetchInterimPVOLRoot()
    }

    func fetchCoverageDays(
        forRadar radar: String,
        years: [String],
        publicBaseURL: URL? = nil,
        rootCatalog: InterimPVOLRootCatalog? = nil
    ) async throws -> [CatalogItem] {
        let root: InterimPVOLRootCatalog
        if let rootCatalog {
            root = rootCatalog
        } else {
            root = try await fetchInterimPVOLRoot()
        }
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
