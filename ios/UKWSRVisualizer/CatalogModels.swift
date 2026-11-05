import Foundation
import SwiftUI

enum RadarAppError: LocalizedError {
    case noCatalogSelection
    case noAggregateURL(String)
    case catalogDecodeFailed(String)
    case downloadSizeMismatch(String, Int64, Int64)
    case hdf5ReadFailed(String)
    case unsupportedFixture(String)

    var errorDescription: String? {
        switch self {
        case .noCatalogSelection:
            return "Select a catalog item first."
        case .noAggregateURL(let item):
            return "No downloadable HDF5 source URL is available for \(item)."
        case .catalogDecodeFailed(let message):
            return "Catalog JSON could not be decoded: \(message)"
        case .downloadSizeMismatch(let name, let expected, let actual):
            return "Downloaded \(name) but the size did not match: expected \(CacheStatus.byteString(expected)), got \(CacheStatus.byteString(actual))."
        case .hdf5ReadFailed(let message):
            return message.isEmpty ? "Could not decode the cached HDF5 scan." : message
        case .unsupportedFixture(let path):
            return "Unsupported local radar fixture: \(path)"
        }
    }
}

struct QuantityRecord: Codable, Hashable, Identifiable {
    var pulse: String
    var time: String
    var dataset: String
    var kind: String
    var index: String
    var quantity: String
    var shape: [Int]
    var dtype: String
    var elevationDeg: Double?
    var nominalHeightM: Double?

    var id: String {
        [pulse, time, dataset, kind, index, quantity].joined(separator: ":")
    }

    enum CodingKeys: String, CodingKey {
        case pulse
        case time
        case dataset
        case kind
        case index
        case quantity
        case shape
        case dtype
        case elevationDeg = "elevation_deg"
        case nominalHeightM = "nominal_height_m"
    }

    init(
        pulse: String,
        time: String,
        dataset: String,
        kind: String,
        index: String,
        quantity: String,
        shape: [Int] = [],
        dtype: String = "",
        elevationDeg: Double? = nil,
        nominalHeightM: Double? = nil
    ) {
        self.pulse = pulse
        self.time = time
        self.dataset = dataset
        self.kind = kind
        self.index = index
        self.quantity = quantity
        self.shape = shape
        self.dtype = dtype
        self.elevationDeg = elevationDeg
        self.nominalHeightM = nominalHeightM
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pulse = try container.decodeIfPresent(String.self, forKey: .pulse) ?? ""
        time = try container.decodeIfPresent(String.self, forKey: .time) ?? ""
        dataset = try container.decodeIfPresent(String.self, forKey: .dataset) ?? ""
        kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? "data"
        index = try container.decodeIfPresent(String.self, forKey: .index) ?? ""
        quantity = try container.decodeIfPresent(String.self, forKey: .quantity) ?? ""
        shape = try container.decodeIfPresent([Int].self, forKey: .shape) ?? []
        dtype = try container.decodeIfPresent(String.self, forKey: .dtype) ?? ""
        elevationDeg = try container.decodeIfPresent(Double.self, forKey: .elevationDeg)
        nominalHeightM = try container.decodeIfPresent(Double.self, forKey: .nominalHeightM)
    }
}

struct RawVolumeRecord: Codable, Hashable, Identifiable {
    var pulse: String
    var time: String
    var path: String
    var filename: String
    var fileSize: Int64
    var modifiedTime: Double
    var objectKey: String
    var objectURL: String
    var quantities: [String]

    var id: String {
        [pulse, time, filename].joined(separator: ":")
    }

    enum CodingKeys: String, CodingKey {
        case pulse
        case time
        case path
        case filename
        case fileSize = "file_size"
        case sizeBytes = "size_bytes"
        case modifiedTime = "modified_time"
        case objectKey = "object_key"
        case objectURL = "object_url"
        case quantities
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pulse = try container.decodeIfPresent(String.self, forKey: .pulse) ?? ""
        time = try container.decodeIfPresent(String.self, forKey: .time) ?? ""
        path = try container.decodeIfPresent(String.self, forKey: .path) ?? ""
        filename = try container.decodeIfPresent(String.self, forKey: .filename) ?? ""
        fileSize = try container.decodeIfPresent(Int64.self, forKey: .fileSize) ??
            container.decodeIfPresent(Int64.self, forKey: .sizeBytes) ?? 0
        modifiedTime = try container.decodeIfPresent(Double.self, forKey: .modifiedTime) ?? 0
        objectKey = try container.decodeIfPresent(String.self, forKey: .objectKey) ?? ""
        objectURL = try container.decodeIfPresent(String.self, forKey: .objectURL) ?? ""
        quantities = try container.decodeIfPresent([String].self, forKey: .quantities) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(pulse, forKey: .pulse)
        try container.encode(time, forKey: .time)
        try container.encode(path, forKey: .path)
        try container.encode(filename, forKey: .filename)
        try container.encode(fileSize, forKey: .fileSize)
        try container.encode(modifiedTime, forKey: .modifiedTime)
        try container.encode(objectKey, forKey: .objectKey)
        try container.encode(objectURL, forKey: .objectURL)
        try container.encode(quantities, forKey: .quantities)
    }

    init(
        pulse: String,
        time: String,
        path: String,
        filename: String,
        fileSize: Int64,
        modifiedTime: Double,
        objectKey: String,
        objectURL: String,
        quantities: [String]
    ) {
        self.pulse = pulse
        self.time = time
        self.path = path
        self.filename = filename
        self.fileSize = fileSize
        self.modifiedTime = modifiedTime
        self.objectKey = objectKey
        self.objectURL = objectURL
        self.quantities = quantities
    }

    init(item: CatalogItem) {
        self.init(item: item, pulse: item.pulses.first ?? item.quantityRecords.first?.pulse ?? "", time: item.times.first ?? item.quantityRecords.first?.time ?? "")
    }

    init(item: CatalogItem, pulse: String, time: String, expectedSize: Int64? = nil) {
        self.pulse = pulse
        self.time = time
        let templateTime = item.times.first ?? item.quantityRecords.first?.time ?? time
        path = item.path
        objectKey = Self.replacingTime(template: item.objectKey, oldTime: templateTime, newTime: time)
        objectURL = Self.replacingTime(template: item.objectURL, oldTime: templateTime, newTime: time)
        filename = objectKey.split(separator: "/").last.map(String.init) ?? "\(item.radar)-\(item.date)-\(pulse)-\(time).h5"
        fileSize = expectedSize ?? item.fileSize
        modifiedTime = item.modifiedTime
        quantities = item.quantities
    }

    private static func replacingTime(template: String, oldTime: String, newTime: String) -> String {
        guard !template.isEmpty, !oldTime.isEmpty, oldTime != newTime else { return template }
        let markers = [".h5", ".hdf5", ".H5", ".HDF5"]
        for marker in markers {
            let needle = "_\(oldTime)\(marker)"
            if template.contains(needle) {
                return template.replacingOccurrences(of: needle, with: "_\(newTime)\(marker)")
            }
        }
        return template.replacingOccurrences(of: "_\(oldTime)_", with: "_\(newTime)_")
    }

    func downloadURL(publicBaseURL: URL) -> URL? {
        if let url = URL(string: objectURL), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return url
        }
        if !objectKey.isEmpty {
            return URL(string: publicBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + objectKey)
        }
        if let url = URL(string: path), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return url
        }
        return nil
    }
}

struct CatalogSpatialMetadata: Codable, Hashable {
    var latitude: Double?
    var longitude: Double?
    var heightM: Double?
    var maxRangeM: Double?
    var bbox: [Double]?
    var source: String?

    enum CodingKeys: String, CodingKey {
        case latitude
        case longitude
        case heightM = "height_m"
        case maxRangeM = "max_range_m"
        case bbox
        case source
    }

    var hasCoordinate: Bool {
        guard let latitude, let longitude else { return false }
        return latitude.isFinite && longitude.isFinite
    }
}

private struct CatalogRootAttributes: Decodable {
    var stringValues: [String: String] = [:]
    var spatialMetadata: CatalogSpatialMetadata?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        for key in container.allKeys {
            if key.stringValue == "uk_wsr:spatial" {
                if let spatial = try? container.decode(CatalogSpatialMetadata.self, forKey: key) {
                    spatialMetadata = spatial
                    continue
                }
                if let spatialString = try? container.decode(String.self, forKey: key),
                   let data = spatialString.data(using: .utf8),
                   let spatial = try? JSONDecoder().decode(CatalogSpatialMetadata.self, from: data) {
                    spatialMetadata = spatial
                    stringValues[key.stringValue] = spatialString
                    continue
                }
            }

            if let value = try? container.decode(String.self, forKey: key) {
                stringValues[key.stringValue] = value
            } else if let value = try? container.decode(Double.self, forKey: key) {
                stringValues[key.stringValue] = String(value)
            } else if let value = try? container.decode(Int.self, forKey: key) {
                stringValues[key.stringValue] = String(value)
            } else if let value = try? container.decode(Bool.self, forKey: key) {
                stringValues[key.stringValue] = value ? "true" : "false"
            }
        }
    }
}

private struct DynamicCodingKey: CodingKey {
    var stringValue: String
    var intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
    }

    init?(intValue: Int) {
        self.stringValue = String(intValue)
        self.intValue = intValue
    }
}

struct CatalogItem: Codable, Hashable, Identifiable {
    var radar: String
    var radarNum: String
    var date: String
    var path: String
    var fileSize: Int64
    var modifiedTime: Double
    var pulses: [String]
    var times: [String]
    var quantities: [String]
    var quantityRecords: [QuantityRecord]
    var objectKey: String
    var objectURL: String
    var rawVolumeCatalogKey: String
    var rawVolumeCatalogURL: String
    var sourceType: String
    var rawVolumes: [RawVolumeRecord]
    var validationStatus: String
    var rootAttrs: [String: String]
    var spatialMetadata: CatalogSpatialMetadata?
    var quantitiesByPulse: [String: [String]]
    var timesByPulse: [String: [String]]

    var id: String {
        [
            radar,
            date,
            sourceType,
            rawVolumeCatalogKey,
            objectKey,
            objectURL,
            path,
        ]
        .filter { !$0.isEmpty }
        .joined(separator: "|")
    }

    var title: String {
        "\(radarDisplayName) \(formattedDate)"
    }

    var radarDisplayName: String {
        radar
            .split(separator: "-")
            .map { part in part.prefix(1).uppercased() + part.dropFirst() }
            .joined(separator: " ")
    }

    var formattedDate: String {
        guard date.count == 8 else { return date }
        let year = date.prefix(4)
        let month = date.dropFirst(4).prefix(2)
        let day = date.suffix(2)
        return "\(year)-\(month)-\(day)"
    }

    enum CodingKeys: String, CodingKey {
        case radar
        case radarNum = "radar_num"
        case date
        case path
        case fileSize = "file_size"
        case modifiedTime = "modified_time"
        case pulses
        case times
        case quantities
        case quantityRecords = "quantity_records"
        case objectKey = "object_key"
        case objectURL = "object_url"
        case rawVolumeCatalogKey = "raw_volume_catalog_key"
        case rawVolumeCatalogURL = "raw_volume_catalog_url"
        case sourceType = "source_type"
        case rawVolumes = "raw_volumes"
        case validationStatus = "validation_status"
        case rootAttrs = "root_attrs"
        case quantitiesByPulse = "quantities_by_pulse"
        case timesByPulse = "times_by_pulse"
    }

    init(
        radar: String,
        radarNum: String = "",
        date: String,
        path: String = "",
        fileSize: Int64 = 0,
        modifiedTime: Double = 0,
        pulses: [String] = [],
        times: [String] = [],
        quantities: [String] = [],
        quantityRecords: [QuantityRecord] = [],
        objectKey: String = "",
        objectURL: String = "",
        rawVolumeCatalogKey: String = "",
        rawVolumeCatalogURL: String = "",
        sourceType: String = "aggregate_day",
        rawVolumes: [RawVolumeRecord] = [],
        validationStatus: String = "unknown",
        rootAttrs: [String: String] = [:],
        spatialMetadata: CatalogSpatialMetadata? = nil,
        quantitiesByPulse: [String: [String]] = [:],
        timesByPulse: [String: [String]] = [:]
    ) {
        self.radar = radar
        self.radarNum = radarNum
        self.date = date
        self.path = path
        self.fileSize = fileSize
        self.modifiedTime = modifiedTime
        self.pulses = pulses
        self.times = times
        self.quantities = quantities
        self.quantityRecords = quantityRecords
        self.objectKey = objectKey
        self.objectURL = objectURL
        self.rawVolumeCatalogKey = rawVolumeCatalogKey
        self.rawVolumeCatalogURL = rawVolumeCatalogURL
        self.sourceType = sourceType
        self.rawVolumes = rawVolumes
        self.validationStatus = validationStatus
        self.rootAttrs = rootAttrs
        self.spatialMetadata = spatialMetadata
        self.quantitiesByPulse = quantitiesByPulse
        self.timesByPulse = timesByPulse
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        radar = try container.decodeIfPresent(String.self, forKey: .radar) ?? ""
        radarNum = try container.decodeIfPresent(String.self, forKey: .radarNum) ?? ""
        date = try container.decodeIfPresent(String.self, forKey: .date) ?? ""
        path = try container.decodeIfPresent(String.self, forKey: .path) ?? ""
        fileSize = try container.decodeIfPresent(Int64.self, forKey: .fileSize) ?? 0
        modifiedTime = try container.decodeIfPresent(Double.self, forKey: .modifiedTime) ?? 0
        pulses = try container.decodeIfPresent([String].self, forKey: .pulses) ?? []
        times = try container.decodeIfPresent([String].self, forKey: .times) ?? []
        quantities = try container.decodeIfPresent([String].self, forKey: .quantities) ?? []
        quantityRecords = try container.decodeIfPresent([QuantityRecord].self, forKey: .quantityRecords) ?? []
        objectKey = try container.decodeIfPresent(String.self, forKey: .objectKey) ?? ""
        objectURL = try container.decodeIfPresent(String.self, forKey: .objectURL) ?? ""
        rawVolumeCatalogKey = try container.decodeIfPresent(String.self, forKey: .rawVolumeCatalogKey) ?? ""
        rawVolumeCatalogURL = try container.decodeIfPresent(String.self, forKey: .rawVolumeCatalogURL) ?? ""
        sourceType = try container.decodeIfPresent(String.self, forKey: .sourceType) ?? "aggregate_day"
        rawVolumes = try container.decodeIfPresent([RawVolumeRecord].self, forKey: .rawVolumes) ?? []
        validationStatus = try container.decodeIfPresent(String.self, forKey: .validationStatus) ?? "unknown"
        if let decodedRootAttrs = try? container.decodeIfPresent(CatalogRootAttributes.self, forKey: .rootAttrs) {
            rootAttrs = decodedRootAttrs.stringValues
            spatialMetadata = decodedRootAttrs.spatialMetadata
        } else {
            rootAttrs = [:]
            spatialMetadata = nil
        }
        quantitiesByPulse = try container.decodeIfPresent([String: [String]].self, forKey: .quantitiesByPulse) ?? [:]
        timesByPulse = try container.decodeIfPresent([String: [String]].self, forKey: .timesByPulse) ?? [:]
    }

    func aggregateURL(publicBaseURL: URL) -> URL? {
        if let url = URL(string: objectURL), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return url
        }
        if let url = URL(string: path), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return url
        }
        if !objectKey.isEmpty {
            return URL(string: publicBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + objectKey)
        }
        return nil
    }

    func rawVolumeCatalogDownloadURL(publicBaseURL: URL) -> URL? {
        if let url = URL(string: rawVolumeCatalogURL), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
            return url
        }
        if !rawVolumeCatalogKey.isEmpty {
            return URL(string: publicBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + rawVolumeCatalogKey)
        }
        return nil
    }

    func rawVolume(for pulse: String, time: String) -> RawVolumeRecord? {
        rawVolumes.first { record in
            (pulse.isEmpty || record.pulse == pulse) && (time.isEmpty || record.time == time)
        }
    }

    func hydrated(with rawItems: [CatalogItem]) -> CatalogItem {
        var copy = self
        let rawVolumes = rawItems.flatMap { rawItem in
            rawItem.expandedRawVolumeRecords()
        }
        let quantityRecords = rawItems.flatMap(\.quantityRecords)
        let pulses = rawItems.flatMap(\.pulses)
        let times = rawItems.flatMap(\.times)
        let quantities = rawItems.flatMap(\.quantities)
        let quantitiesByPulse = Dictionary(grouping: quantityRecords, by: \.pulse)
            .mapValues { records in Array(Set(records.map(\.quantity))).sorted() }
        let timesByPulse = Dictionary(grouping: quantityRecords, by: \.pulse)
            .mapValues { records in Array(Set(records.map(\.time))).sorted() }

        copy.rawVolumes = rawVolumes
        if !quantityRecords.isEmpty {
            copy.quantityRecords = quantityRecords
        }
        if !pulses.isEmpty {
            copy.pulses = Array(Set(pulses)).sorted()
        }
        if !times.isEmpty {
            copy.times = Array(Set(times)).sorted()
        }
        if !quantities.isEmpty {
            copy.quantities = Array(Set(quantities)).sorted()
        }
        if !quantitiesByPulse.isEmpty {
            copy.quantitiesByPulse = quantitiesByPulse
        }
        if !timesByPulse.isEmpty {
            copy.timesByPulse = timesByPulse
        }
        return copy
    }

    private func expandedRawVolumeRecords() -> [RawVolumeRecord] {
        let recordTimes = quantityRecords.map(\.time).filter { !$0.isEmpty }
        let expandedTimes = Array(Set(times + recordTimes)).sorted()
        let pulses = Array(Set((pulses + quantityRecords.map(\.pulse)).filter { !$0.isEmpty })).sorted()
        guard !expandedTimes.isEmpty else {
            return [RawVolumeRecord(item: self)]
        }
        let sizeIsPerExpandedScan = expandedTimes.count == 1
        return pulses.flatMap { pulse in
            expandedTimes.map { time in
                RawVolumeRecord(
                    item: self,
                    pulse: pulse,
                    time: time,
                    expectedSize: sizeIsPerExpandedScan ? fileSize : 0
                )
            }
        }
    }
}

struct CatalogEnvelope: Codable {
    var version: Int?
    var items: [CatalogItem]
}

struct InterimPVOLRootCatalog: Decodable {
    var schemaVersion: Int?
    var generatedAt: String?
    var interim: Bool
    var uploadComplete: Bool
    var fileCount: Int
    var sizeBytes: Int64
    var radars: [InterimPVOLRadar]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case interim
        case uploadComplete = "upload_complete"
        case fileCount = "file_count"
        case sizeBytes = "size_bytes"
        case radars
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        interim = try container.decodeIfPresent(Bool.self, forKey: .interim) ?? false
        uploadComplete = try container.decodeIfPresent(Bool.self, forKey: .uploadComplete) ?? true
        fileCount = try container.decodeIfPresent(Int.self, forKey: .fileCount) ?? 0
        sizeBytes = try container.decodeIfPresent(Int64.self, forKey: .sizeBytes) ?? 0
        radars = try container.decodeIfPresent([InterimPVOLRadar].self, forKey: .radars) ?? []
    }
}

struct InterimPVOLRadar: Decodable, Hashable {
    var radar: String
    var radarNum: String
    var years: [String]
    var coverageKeys: [String]
    var firstDate: String
    var lastDate: String
    var dateCount: Int
    var fileCount: Int
    var sizeBytes: Int64
    var spatial: CatalogSpatialMetadata?

    enum CodingKeys: String, CodingKey {
        case radar
        case radarNum = "radar_num"
        case years
        case coverageKeys = "coverage_keys"
        case firstDate = "first_date"
        case lastDate = "last_date"
        case dateCount = "date_count"
        case fileCount = "file_count"
        case sizeBytes = "size_bytes"
        case spatial
    }
}

struct InterimPVOLCoverage: Decodable {
    var schemaVersion: Int?
    var generatedAt: String?
    var interim: Bool
    var uploadComplete: Bool
    var radar: String
    var year: String
    var days: [InterimPVOLDay]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case interim
        case uploadComplete = "upload_complete"
        case radar
        case year
        case days
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        interim = try container.decodeIfPresent(Bool.self, forKey: .interim) ?? false
        uploadComplete = try container.decodeIfPresent(Bool.self, forKey: .uploadComplete) ?? true
        radar = try container.decodeIfPresent(String.self, forKey: .radar) ?? ""
        year = try container.decodeIfPresent(String.self, forKey: .year) ?? ""
        days = try container.decodeIfPresent([InterimPVOLDay].self, forKey: .days) ?? []
    }
}

struct InterimPVOLDay: Decodable, Hashable {
    var date: String
    var catalogKey: String
    var pvolPrefix: String
    var fileCount: Int
    var sizeBytes: Int64
    var pulseCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case date
        case catalogKey = "catalog_key"
        case pvolPrefix = "pvol_prefix"
        case fileCount = "file_count"
        case sizeBytes = "size_bytes"
        case pulseCounts = "pulse_counts"
    }
}

struct InterimPVOLDayCatalog: Decodable {
    var schemaVersion: Int?
    var generatedAt: String?
    var interim: Bool
    var uploadComplete: Bool
    var radar: String
    var radarNum: String
    var date: String
    var catalogKey: String
    var pvolPrefix: String
    var fileCount: Int
    var sizeBytes: Int64
    var pulses: [String]
    var pulseCounts: [String: Int]
    var timesByPulse: [String: [String]]
    var files: [InterimPVOLFile]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case interim
        case uploadComplete = "upload_complete"
        case radar
        case radarNum = "radar_num"
        case date
        case catalogKey = "catalog_key"
        case pvolPrefix = "pvol_prefix"
        case fileCount = "file_count"
        case sizeBytes = "size_bytes"
        case pulses
        case pulseCounts = "pulse_counts"
        case timesByPulse = "times_by_pulse"
        case files
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        interim = try container.decodeIfPresent(Bool.self, forKey: .interim) ?? false
        uploadComplete = try container.decodeIfPresent(Bool.self, forKey: .uploadComplete) ?? true
        radar = try container.decodeIfPresent(String.self, forKey: .radar) ?? ""
        radarNum = try container.decodeIfPresent(String.self, forKey: .radarNum) ?? ""
        date = try container.decodeIfPresent(String.self, forKey: .date) ?? ""
        catalogKey = try container.decodeIfPresent(String.self, forKey: .catalogKey) ?? ""
        pvolPrefix = try container.decodeIfPresent(String.self, forKey: .pvolPrefix) ?? ""
        fileCount = try container.decodeIfPresent(Int.self, forKey: .fileCount) ?? 0
        sizeBytes = try container.decodeIfPresent(Int64.self, forKey: .sizeBytes) ?? 0
        pulses = try container.decodeIfPresent([String].self, forKey: .pulses) ?? []
        pulseCounts = try container.decodeIfPresent([String: Int].self, forKey: .pulseCounts) ?? [:]
        timesByPulse = try container.decodeIfPresent([String: [String]].self, forKey: .timesByPulse) ?? [:]
        files = try container.decodeIfPresent([InterimPVOLFile].self, forKey: .files) ?? []
    }
}

struct InterimPVOLFile: Decodable, Hashable {
    var pulse: String
    var time: String
    var filename: String
    var sizeBytes: Int64
    var modifiedTime: Double
    var objectKey: String
    var objectURL: String

    enum CodingKeys: String, CodingKey {
        case pulse
        case time
        case filename
        case sizeBytes = "size_bytes"
        case modifiedTime = "modified_time"
        case objectKey = "object_key"
        case objectURL = "object_url"
    }
}

extension CatalogItem {
    init(interimPVOLDay day: InterimPVOLDay, radar: InterimPVOLRadar, root: InterimPVOLRootCatalog) {
        let pulses = day.pulseCounts.keys.sorted()
        var rootAttrs = [
            "interim": String(root.interim),
            "upload_complete": String(root.uploadComplete),
            "file_count": String(day.fileCount),
            "catalog_key": day.catalogKey,
        ]
        if let spatial = radar.spatial {
            if let latitude = spatial.latitude {
                rootAttrs["radar_latitude"] = String(latitude)
            }
            if let longitude = spatial.longitude {
                rootAttrs["radar_longitude"] = String(longitude)
            }
            if let heightM = spatial.heightM {
                rootAttrs["radar_height_m"] = String(heightM)
            }
            if let source = spatial.source, !source.isEmpty {
                rootAttrs["radar_spatial_source"] = source
            }
        }
        self.init(
            radar: radar.radar,
            radarNum: radar.radarNum,
            date: day.date,
            path: day.pvolPrefix,
            fileSize: day.sizeBytes,
            pulses: pulses,
            rawVolumeCatalogKey: day.catalogKey,
            sourceType: "raw_volume_day",
            validationStatus: root.interim ? "interim" : "published",
            rootAttrs: rootAttrs,
            spatialMetadata: radar.spatial,
            timesByPulse: Dictionary(uniqueKeysWithValues: pulses.map { ($0, []) })
        )
    }

    init(interimPVOLFile file: InterimPVOLFile, day: InterimPVOLDayCatalog) {
        self.init(
            radar: day.radar,
            radarNum: day.radarNum,
            date: day.date,
            path: file.objectURL,
            fileSize: file.sizeBytes,
            modifiedTime: file.modifiedTime,
            pulses: file.pulse.isEmpty ? [] : [file.pulse],
            times: file.time.isEmpty ? [] : [file.time],
            objectKey: file.objectKey,
            objectURL: file.objectURL,
            sourceType: "raw_volume_file",
            validationStatus: day.interim ? "interim" : "published",
            rootAttrs: [
                "interim": String(day.interim),
                "upload_complete": String(day.uploadComplete),
                "catalog_key": day.catalogKey,
                "pvol_prefix": day.pvolPrefix,
            ],
            timesByPulse: file.pulse.isEmpty || file.time.isEmpty ? [:] : [file.pulse: [file.time]]
        )
    }
}
