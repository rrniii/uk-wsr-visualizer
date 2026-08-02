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

struct RadarGridMetadata: Hashable {
    var radar: String
    var date: String
    var pulse: String
    var time: String
    var quantity: String
    var dataset: String
    var latitude: Double
    var longitude: Double
    var heightM: Double?
    var elevationDeg: Double?
    var rstartKm: Double
    var rscaleM: Double
    var nbins: Int
    var nrays: Int

    var maxRangeM: Double {
        rstartKm * 1000 + rscaleM * Double(nbins)
    }
}

struct FieldSelection: Hashable {
    var pulse: String
    var time: String
    var quantity: String
    var dataset: String?
    var cappiHeightM: Double?
}

enum DisplayRangeMode: String, CaseIterable, Identifiable, Hashable {
    case standard
    case dataStretch
    case custom

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .standard:
            return "Standard"
        case .dataStretch:
            return "Data stretch"
        case .custom:
            return "Custom"
        }
    }

    var detail: String {
        switch self {
        case .standard:
            return "Uses sensible fixed limits for the selected variable."
        case .dataStretch:
            return "Fits the colour scale to the current scan."
        case .custom:
            return "Uses the min and max values below."
        }
    }
}

struct RadarFilterSet: Hashable {
    var minRangeKm: Double?
    var maxRangeKm: Double?
    var minAzimuthDeg: Double?
    var maxAzimuthDeg: Double?
    var minValue: Double?
    var maxValue: Double?
    var cappiHeightM: Double?
    var displayRangeMode: DisplayRangeMode = .standard
    var displayMin: Double?
    var displayMax: Double?
    var palette: String = "auto"
    var opacity: Double = 0.88
    var noiseFloorEnabled: Bool = true
    var noiseFloorMethod: String = "estimated"
    var noiseFloorMarginDb: Double = 0
    var noiseFloorOperation: String = "mask"
    var noiseFloorPercentile: Double = 10
    var noiseFloorWindowBins: Int = 11
    var qcRuntimeMode: QCV3RuntimeMode = .safe
    var qcValidatedBundleID: String?
    var experimentalLongRangeNoiseEnabled: Bool = false
    var receiverNoiseEnabled: Bool = true
    var receiverNoiseMarginDb: Double = 0.25
    var receiverNoiseSqiMax: Double = 0.05
    var receiverNoiseRhohvMax: Double = 0.20
    var receiverNoisePhiDPTextureMin: Double = 60
    var receiverNoiseVelocityTextureMin: Double = 9
    var receiverNoiseMinBadMoments: Int = 3
    var ambientNoiseRayExcessDb: Double = 3
    var ciEvidenceEnabled: Bool = true
    var ciNoiseMinDb: Double = 6
    var ciClutterMaxDb: Double = 2
    var textureCleanupEnabled: Bool = false
    var textureThresholdDb: Double = 10
    var textureNearMarginDb: Double = 14
    var textureSupportDb: Double = 6
    var textureMaxDbz: Double = 30
    var textureMinSimilarNeighbors: Int = 1
    var companionQcEnabled: Bool = false
    var staticClutterEnabled: Bool = false
    var staticClutterDbzMin: Double = 5
    var staticClutterVradAbsMax: Double = 1
    var staticClutterMinNeighbors: Int = 3
    // Candidate 8 models remain quarantined and shadow-only until the real-data
    // preservation and release gates pass.
    var backgroundModelEnabled: Bool = false
    var backgroundPersistentFrequencyMin: Double = 0.95
    var backgroundMinSamples: Int = 40
    var backgroundStaticVradFrequencyMin: Double = 0.80
    var backgroundLowSqiFrequencyMin: Double = 0.40
    var backgroundDbzhExcessMaxDb: Double = 3
    var backgroundEvidenceScoreThreshold: Int = 3
    var backgroundCurrentVradAbsMax: Double = 0.5
    var backgroundLearnedLowCiFrequencyMin: Double = 0.60
    var backgroundRequireTrainingDiversity: Bool = true
    var backgroundMinTrainingDates: Int = 12
    var backgroundMinTrainingSpanDays: Int = 90
}

enum QCV3RuntimeMode: String, Codable, Hashable {
    case safe
    case shadow
    case validated
}

struct QCV3ReasonFlag: OptionSet, Hashable {
    let rawValue: UInt16

    static let receiverNoise = QCV3ReasonFlag(rawValue: 1 << 2)
    static let persistentGroundClutter = QCV3ReasonFlag(rawValue: 1 << 3)
}

struct QCV3RuntimeResult: Hashable {
    var version = "qc-v3"
    var mode: QCV3RuntimeMode
    var removalMask: [Bool]
    var proposedRemovalMask: [Bool]
    var abstentionMask: [Bool]
    var reasonFlags: [UInt16]
    var learnedCandidateApplied: Bool
    var bundleQualification: String

    var removedCount: Int {
        removalMask.filter { $0 }.count
    }

    var proposedRemovedCount: Int {
        proposedRemovalMask.filter { $0 }.count
    }
}

struct NoiseFloorResult: Hashable {
    var enabled: Bool
    var method: String = "none"
    var operation: String = "none"
    var sourceQuantity: String?
    var marginDb: Double?
    var percentile: Double?
    var windowBins: Int?
    var maskedCount: Int = 0
    var finiteBefore: Int = 0
    var finiteAfter: Int = 0
    var floorProfile: [Double?] = []
}

struct BackgroundModelResult: Hashable {
    var enabled: Bool
    var applied: Bool = false
    var modelKey: String?
    var maskedCount: Int = 0
    var finiteBefore: Int = 0
    var finiteAfter: Int = 0
    var reason: String?
}

struct BackgroundModel: Hashable, Decodable {
    static let candidate8StatisticsVersion = "date-balanced-static-v3"
    var key: [String: String] = [:]
    var rows: Int
    var columns: Int
    var sampleCount: [Float]
    var persistentEchoFrequency: [Float]
    var dbzhP90: [Float]
    var nearZeroVradFrequency: [Float] = []
    var lowSqiFrequency: [Float] = []
    var lowRhohvFrequency: [Float] = []
    var unstableRhohvFrequency: [Float] = []
    var zdrOutlierFrequency: [Float] = []
    var unstableZdrFrequency: [Float] = []
    var ciSampleCount: [Float] = []
    var lowCiFrequency: [Float] = []
    var highCiFrequency: [Float] = []
    var staticEchoDateSampleCount: [Float] = []
    var staticEchoDateFrequency: [Float] = []
    var staticEchoSeasonCount: [Float] = []
    var staticEchoTimeBucketCount: [Float] = []
    var staticDBZHP10: [Float] = []
    var staticDBZHMedian: [Float] = []
    var staticDBZHP90: [Float] = []
    var sourceDateCount: Int = 0
    var trainingSpanDays: Int = 0
    var sourceYearCount: Int = 0
    var seasonDateCounts: [String: Int] = [:]
    var timeBucketDateCounts: [String: Int] = [:]
    var statisticsVersion: String?

    enum CodingKeys: String, CodingKey {
        case key
        case shape
        case inlineArrays = "inline_arrays"
        case rows
        case columns
        case sampleCount = "sample_count"
        case persistentEchoFrequency = "persistent_echo_frequency"
        case dbzhP90 = "dbzh_p90"
        case nearZeroVradFrequency = "near_zero_vrad_frequency"
        case lowSqiFrequency = "low_sqi_frequency"
        case lowRhohvFrequency = "low_rhohv_frequency"
        case unstableRhohvFrequency = "unstable_rhohv_frequency"
        case zdrOutlierFrequency = "zdr_outlier_frequency"
        case unstableZdrFrequency = "unstable_zdr_frequency"
        case ciSampleCount = "ci_sample_count"
        case lowCiFrequency = "low_ci_frequency"
        case highCiFrequency = "high_ci_frequency"
        case staticEchoDateSampleCount = "low_ci_static_echo_date_sample_count"
        case staticEchoDateFrequency = "low_ci_static_echo_date_frequency"
        case staticEchoSeasonCount = "low_ci_static_echo_season_count"
        case staticEchoTimeBucketCount = "low_ci_static_echo_time_bucket_count"
        case staticDBZHP10 = "low_ci_static_dbzh_p10"
        case staticDBZHMedian = "low_ci_static_dbzh_median"
        case staticDBZHP90 = "low_ci_static_dbzh_p90"
        case metadata
    }

    var modelKey: String {
        key.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: ",")
    }

    func matches(metadata: RadarGridMetadata, gateQuantity: String?) -> Bool {
        guard matchesStringKey("radar", actual: metadata.radar),
              matchesStringKey("pulse", actual: metadata.pulse),
              matchesStringKey("dataset", actual: Self.normalizedDataset(metadata.dataset)),
              matchesStringKey("quantity", actual: (gateQuantity ?? metadata.quantity).trimmingCharacters(in: .whitespacesAndNewlines).uppercased()) else {
            return false
        }
        if let expected = key["elevation_deg"], !expected.isEmpty {
            guard let expectedElevation = Double(expected), let actualElevation = metadata.elevationDeg else {
                return false
            }
            if abs(actualElevation - expectedElevation) > 0.05 {
                return false
            }
        }
        return true
    }

    func trainingQualificationFailure(minimumDates: Int, minimumSpanDays: Int) -> String? {
        if sourceDateCount < minimumDates {
            return "insufficient_training_dates:\(sourceDateCount)<\(minimumDates)"
        }
        if trainingSpanDays < minimumSpanDays {
            return "insufficient_training_span_days:\(trainingSpanDays)<\(minimumSpanDays)"
        }
        return nil
    }

    var seasonalBucketsQualified: Bool {
        sourceYearCount >= 2
            && ["winter", "spring", "summer", "autumn"].allSatisfy {
                seasonDateCounts[$0, default: 0] >= 12
            }
    }

    var timeBucketsQualified: Bool {
        ["day", "night"].allSatisfy {
            timeBucketDateCounts[$0, default: 0] >= 12
        }
    }

    private func matchesStringKey(_ name: String, actual: String) -> Bool {
        guard let expected = key[name], !expected.isEmpty else {
            return true
        }
        let expectedValue = name == "dataset" ? Self.normalizedDataset(expected) : expected.trimmingCharacters(in: .whitespacesAndNewlines)
        return expectedValue.caseInsensitiveCompare(actual) == .orderedSame
    }

    private static func normalizedDataset(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return trimmed.allSatisfy(\.isNumber) && !trimmed.isEmpty ? "dataset\(trimmed)" : trimmed
    }

    init(
        key: [String: String] = [:],
        rows: Int,
        columns: Int,
        sampleCount: [Float],
        persistentEchoFrequency: [Float],
        dbzhP90: [Float],
        nearZeroVradFrequency: [Float] = [],
        lowSqiFrequency: [Float] = [],
        lowRhohvFrequency: [Float] = [],
        unstableRhohvFrequency: [Float] = [],
        zdrOutlierFrequency: [Float] = [],
        unstableZdrFrequency: [Float] = [],
        ciSampleCount: [Float] = [],
        lowCiFrequency: [Float] = [],
        highCiFrequency: [Float] = [],
        staticEchoDateSampleCount: [Float] = [],
        staticEchoDateFrequency: [Float] = [],
        staticEchoSeasonCount: [Float] = [],
        staticEchoTimeBucketCount: [Float] = [],
        staticDBZHP10: [Float] = [],
        staticDBZHMedian: [Float] = [],
        staticDBZHP90: [Float] = [],
        sourceDateCount: Int = 0,
        trainingSpanDays: Int = 0,
        sourceYearCount: Int = 0,
        seasonDateCounts: [String: Int] = [:],
        timeBucketDateCounts: [String: Int] = [:],
        statisticsVersion: String? = nil
    ) {
        self.key = key
        self.rows = rows
        self.columns = columns
        self.sampleCount = sampleCount
        self.persistentEchoFrequency = persistentEchoFrequency
        self.dbzhP90 = dbzhP90
        self.nearZeroVradFrequency = nearZeroVradFrequency
        self.lowSqiFrequency = lowSqiFrequency
        self.lowRhohvFrequency = lowRhohvFrequency
        self.unstableRhohvFrequency = unstableRhohvFrequency
        self.zdrOutlierFrequency = zdrOutlierFrequency
        self.unstableZdrFrequency = unstableZdrFrequency
        self.ciSampleCount = ciSampleCount
        self.lowCiFrequency = lowCiFrequency
        self.highCiFrequency = highCiFrequency
        self.staticEchoDateSampleCount = staticEchoDateSampleCount
        self.staticEchoDateFrequency = staticEchoDateFrequency
        self.staticEchoSeasonCount = staticEchoSeasonCount
        self.staticEchoTimeBucketCount = staticEchoTimeBucketCount
        self.staticDBZHP10 = staticDBZHP10
        self.staticDBZHMedian = staticDBZHMedian
        self.staticDBZHP90 = staticDBZHP90
        self.sourceDateCount = sourceDateCount
        self.trainingSpanDays = trainingSpanDays
        self.sourceYearCount = sourceYearCount
        self.seasonDateCounts = seasonDateCounts
        self.timeBucketDateCounts = timeBucketDateCounts
        self.statisticsVersion = statisticsVersion
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        key = ((try? container.decode([String: StringBackedValue].self, forKey: .key)) ?? [:])
            .mapValues { $0.value }
        if let shape = try? container.decode([Int].self, forKey: .shape), shape.count >= 2 {
            rows = shape[0]
            columns = shape[1]
        } else {
            rows = try container.decode(Int.self, forKey: .rows)
            columns = try container.decode(Int.self, forKey: .columns)
        }
        let inlineArrays = (try? container.decode([String: InlineArrayPayload].self, forKey: .inlineArrays)) ?? [:]
        sampleCount = Self.decodeOptionalArray(
            .sampleCount,
            inlineNames: ["sample_count"],
            from: container,
            inlineArrays: inlineArrays
        )
        persistentEchoFrequency = Self.decodeOptionalArray(
            .persistentEchoFrequency,
            inlineNames: ["persistent_echo_frequency"],
            from: container,
            inlineArrays: inlineArrays
        )
        dbzhP90 = Self.decodeOptionalArray(
            .dbzhP90,
            inlineNames: ["dbzh_p90"],
            from: container,
            inlineArrays: inlineArrays
        )
        nearZeroVradFrequency = Self.decodeOptionalArray(
            .nearZeroVradFrequency,
            inlineName: "near_zero_vrad_frequency",
            from: container,
            inlineArrays: inlineArrays
        )
        lowSqiFrequency = Self.decodeOptionalArray(.lowSqiFrequency, inlineName: "low_sqi_frequency", from: container, inlineArrays: inlineArrays)
        lowRhohvFrequency = Self.decodeOptionalArray(.lowRhohvFrequency, inlineName: "low_rhohv_frequency", from: container, inlineArrays: inlineArrays)
        unstableRhohvFrequency = Self.decodeOptionalArray(
            .unstableRhohvFrequency,
            inlineName: "unstable_rhohv_frequency",
            from: container,
            inlineArrays: inlineArrays
        )
        zdrOutlierFrequency = Self.decodeOptionalArray(.zdrOutlierFrequency, inlineName: "zdr_outlier_frequency", from: container, inlineArrays: inlineArrays)
        unstableZdrFrequency = Self.decodeOptionalArray(.unstableZdrFrequency, inlineName: "unstable_zdr_frequency", from: container, inlineArrays: inlineArrays)
        ciSampleCount = Self.decodeOptionalArray(.ciSampleCount, inlineName: "ci_sample_count", from: container, inlineArrays: inlineArrays)
        lowCiFrequency = Self.decodeOptionalArray(.lowCiFrequency, inlineName: "low_ci_frequency", from: container, inlineArrays: inlineArrays)
        highCiFrequency = Self.decodeOptionalArray(.highCiFrequency, inlineName: "high_ci_frequency", from: container, inlineArrays: inlineArrays)
        staticEchoDateSampleCount = Self.decodeOptionalArray(
            .staticEchoDateSampleCount,
            inlineNames: [
                "static_echo_date_sample_count",
                "low_ci_static_echo_date_sample_count",
            ],
            from: container,
            inlineArrays: inlineArrays
        )
        staticEchoDateFrequency = Self.decodeOptionalArray(
            .staticEchoDateFrequency,
            inlineNames: [
                "static_echo_date_frequency",
                "low_ci_static_echo_date_frequency",
            ],
            from: container,
            inlineArrays: inlineArrays
        )
        staticEchoSeasonCount = Self.decodeOptionalArray(
            .staticEchoSeasonCount,
            inlineNames: [
                "static_echo_season_count",
                "low_ci_static_echo_season_count",
            ],
            from: container,
            inlineArrays: inlineArrays
        )
        staticEchoTimeBucketCount = Self.decodeOptionalArray(
            .staticEchoTimeBucketCount,
            inlineNames: [
                "static_echo_time_bucket_count",
                "low_ci_static_echo_time_bucket_count",
            ],
            from: container,
            inlineArrays: inlineArrays
        )
        staticDBZHP10 = Self.decodeOptionalArray(
            .staticDBZHP10,
            inlineNames: ["static_dbzh_p10", "low_ci_static_dbzh_p10"],
            from: container,
            inlineArrays: inlineArrays
        )
        staticDBZHMedian = Self.decodeOptionalArray(
            .staticDBZHMedian,
            inlineNames: [
                "static_dbzh_median",
                "low_ci_static_dbzh_median",
            ],
            from: container,
            inlineArrays: inlineArrays
        )
        staticDBZHP90 = Self.decodeOptionalArray(
            .staticDBZHP90,
            inlineNames: ["static_dbzh_p90", "low_ci_static_dbzh_p90"],
            from: container,
            inlineArrays: inlineArrays
        )
        let trainingMetadata = try? container.decode(TrainingMetadata.self, forKey: .metadata)
        sourceDateCount = trainingMetadata?.sourceDateCount ?? (trainingMetadata?.firstSourceDate == nil ? 0 : 1)
        trainingSpanDays = trainingMetadata?.trainingSpanDays ?? 0
        sourceYearCount = trainingMetadata?.sourceYearCount ?? 0
        seasonDateCounts = trainingMetadata?.seasonDateCounts ?? [:]
        timeBucketDateCounts = trainingMetadata?.timeBucketDateCounts ?? [:]
        statisticsVersion = trainingMetadata?.statisticsVersion
    }

    static func load(from url: URL) throws -> BackgroundModel {
        try JSONDecoder().decode(BackgroundModel.self, from: Data(contentsOf: url))
    }

    private static func decodeOptionalArray(
        _ key: CodingKeys,
        inlineName: String,
        from container: KeyedDecodingContainer<CodingKeys>,
        inlineArrays: [String: InlineArrayPayload]
    ) -> [Float] {
        if let values = try? container.decode([Float].self, forKey: key) {
            return values
        }
        if let payload = inlineArrays[inlineName], let values = try? payload.floatValues() {
            return values
        }
        return []
    }

    private static func decodeOptionalArray(
        _ key: CodingKeys,
        inlineNames: [String],
        from container: KeyedDecodingContainer<CodingKeys>,
        inlineArrays: [String: InlineArrayPayload]
    ) -> [Float] {
        if let values = try? container.decode([Float].self, forKey: key) {
            return values
        }
        for name in inlineNames {
            if let payload = inlineArrays[name],
               let values = try? payload.floatValues() {
                return values
            }
        }
        return []
    }

    private struct StringBackedValue: Decodable {
        var value: String

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let string = try? container.decode(String.self) {
                value = string
            } else if let int = try? container.decode(Int.self) {
                value = String(int)
            } else if let double = try? container.decode(Double.self) {
                value = String(double)
            } else if let bool = try? container.decode(Bool.self) {
                value = String(bool)
            } else {
                value = ""
            }
        }
    }

    private struct TrainingMetadata: Decodable {
        var sourceDateCount: Int?
        var trainingSpanDays: Int?
        var sourceYearCount: Int?
        var seasonDateCounts: [String: Int]?
        var timeBucketDateCounts: [String: Int]?
        var statisticsVersion: String?
        var firstSource: FirstSource?

        enum CodingKeys: String, CodingKey {
            case sourceDateCount = "source_date_count"
            case trainingSpanDays = "training_span_days"
            case sourceYearCount = "source_year_count"
            case seasonDateCounts = "season_date_counts"
            case timeBucketDateCounts = "time_bucket_date_counts"
            case statisticsVersion = "statistics_version"
            case firstSource = "first_source"
        }

        var firstSourceDate: String? { firstSource?.date }

        struct FirstSource: Decodable {
            var date: String?
        }
    }

    private struct InlineArrayPayload: Decodable {
        var dtype: String
        var shape: [Int]
        var encoding: String
        var data: String
        var scale: Float?
        var offset: Float?
        var nanSentinel: Int?

        enum CodingKeys: String, CodingKey {
            case dtype
            case shape
            case encoding
            case data
            case scale
            case offset
            case nanSentinel = "nan_sentinel"
        }

        func floatValues() throws -> [Float] {
            guard encoding == "base64", let bytes = Data(base64Encoded: data) else {
                throw DecodingError.dataCorrupted(
                    DecodingError.Context(codingPath: [], debugDescription: "Unsupported inline array")
                )
            }
            let raw = [UInt8](bytes)
            let normalizedDtype = dtype.lowercased()
            if normalizedDtype == "uint8" {
                return raw.map { Float($0) * (scale ?? 1) + (offset ?? 0) }
            }
            if ["uint16", "<u2", "u2"].contains(normalizedDtype) {
                guard raw.count % 2 == 0 else {
                    throw DecodingError.dataCorrupted(
                        DecodingError.Context(codingPath: [], debugDescription: "Malformed inline uint16 array")
                    )
                }
                var values = [Float]()
                values.reserveCapacity(raw.count / 2)
                var byteOffset = 0
                while byteOffset + 1 < raw.count {
                    let value = UInt16(raw[byteOffset]) | (UInt16(raw[byteOffset + 1]) << 8)
                    values.append(Float(value) * (scale ?? 1) + (offset ?? 0))
                    byteOffset += 2
                }
                return values
            }
            if ["int16", "<i2", "i2"].contains(normalizedDtype) {
                guard raw.count % 2 == 0 else {
                    throw DecodingError.dataCorrupted(
                        DecodingError.Context(codingPath: [], debugDescription: "Malformed inline int16 array")
                    )
                }
                var values = [Float]()
                values.reserveCapacity(raw.count / 2)
                var byteOffset = 0
                while byteOffset + 1 < raw.count {
                    let bits = UInt16(raw[byteOffset]) | (UInt16(raw[byteOffset + 1]) << 8)
                    let signed = Int16(bitPattern: bits)
                    if let nanSentinel, Int(signed) == nanSentinel {
                        values.append(Float.nan)
                    } else {
                        values.append(Float(signed) * (scale ?? 1) + (offset ?? 0))
                    }
                    byteOffset += 2
                }
                return values
            }
            guard ["float32", "<f4", "f4"].contains(normalizedDtype), raw.count % 4 == 0 else {
                throw DecodingError.dataCorrupted(
                    DecodingError.Context(codingPath: [], debugDescription: "Unsupported inline float32 array")
                )
            }
            var values = [Float]()
            values.reserveCapacity(raw.count / 4)
            var byteOffset = 0
            while byteOffset + 3 < raw.count {
                let bits = UInt32(raw[byteOffset]) |
                    (UInt32(raw[byteOffset + 1]) << 8) |
                    (UInt32(raw[byteOffset + 2]) << 16) |
                    (UInt32(raw[byteOffset + 3]) << 24)
                values.append(Float(bitPattern: bits))
                byteOffset += 4
            }
            return values
        }
    }
}

struct BackgroundModelDescriptor: Hashable {
    var url: URL
    var key: [String: String]
    var rows: Int
    var columns: Int
    var eligibleForValidatedRuntime: Bool = false

    var modelKey: String {
        key.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: ",")
    }

    func matches(metadata: RadarGridMetadata, gateQuantity: String?) -> Bool {
        guard matchesStringKey("radar", actual: metadata.radar),
              matchesStringKey("pulse", actual: metadata.pulse),
              matchesStringKey("dataset", actual: Self.normalizedDataset(metadata.dataset)),
              matchesStringKey("quantity", actual: (gateQuantity ?? metadata.quantity).trimmingCharacters(in: .whitespacesAndNewlines).uppercased()) else {
            return false
        }
        if let expected = key["elevation_deg"], !expected.isEmpty {
            guard let expectedElevation = Double(expected), let actualElevation = metadata.elevationDeg else {
                return false
            }
            if abs(actualElevation - expectedElevation) > 0.05 {
                return false
            }
        }
        return true
    }

    static func load(
        from url: URL,
        eligibleForValidatedRuntime: Bool = false
    ) throws -> BackgroundModelDescriptor {
        let header = try JSONDecoder().decode(Header.self, from: Data(contentsOf: url))
        let shapeRows: Int
        let shapeColumns: Int
        if let shape = header.shape, shape.count >= 2 {
            shapeRows = shape[0]
            shapeColumns = shape[1]
        } else {
            shapeRows = header.rows ?? 0
            shapeColumns = header.columns ?? 0
        }
        return BackgroundModelDescriptor(
            url: url,
            key: header.key.mapValues { $0.value },
            rows: shapeRows,
            columns: shapeColumns,
            eligibleForValidatedRuntime: eligibleForValidatedRuntime
        )
    }

    private func matchesStringKey(_ name: String, actual: String) -> Bool {
        guard let expected = key[name], !expected.isEmpty else {
            return true
        }
        let expectedValue = name == "dataset" ? Self.normalizedDataset(expected) : expected.trimmingCharacters(in: .whitespacesAndNewlines)
        return expectedValue.caseInsensitiveCompare(actual) == .orderedSame
    }

    private static func normalizedDataset(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return trimmed.allSatisfy(\.isNumber) && !trimmed.isEmpty ? "dataset\(trimmed)" : trimmed
    }

    private struct Header: Decodable {
        var key: [String: StringBackedValue]
        var shape: [Int]?
        var rows: Int?
        var columns: Int?
    }

    private struct StringBackedValue: Decodable {
        var value: String

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if let string = try? container.decode(String.self) {
                value = string
            } else if let int = try? container.decode(Int.self) {
                value = String(int)
            } else if let double = try? container.decode(Double.self) {
                value = String(double)
            } else if let bool = try? container.decode(Bool.self) {
                value = String(bool)
            } else {
                value = ""
            }
        }
    }
}

struct BackgroundModelRegistry: Decodable {
    static let schemaName = "uk_wsr_background_model_manifest"
    static let minimumSchemaVersion = 3
    static let requiredQCVersion = "qc-v3-candidate-8"
    static let requiredContractSHA256 = "177b3534085f4571f014b5060527562202527a626ee1d907bb54ed8dd6162336"

    var schema: String
    var schemaVersion: Int
    var runtimeStatus: String?
    var contract: Candidate8RuntimeContract?
    var contractSHA256: String?
    var models: [Entry]

    enum CodingKeys: String, CodingKey {
        case schema
        case schemaVersion = "schema_version"
        case runtimeStatus = "runtime_status"
        case contract
        case contractSHA256 = "contract_sha256"
        case models
    }

    struct Candidate8RuntimeContract: Decodable {
        var schema: String
        var schemaVersion: Int
        var evidenceVersion: String
        var backgroundStatisticsVersion: String
        var runtimeStatus: String
        var eligibleForDefault: Bool
        var modelArrays: [String]
        var missingFieldPolicy: [String: String]

        enum CodingKeys: String, CodingKey {
            case schema
            case schemaVersion = "schema_version"
            case evidenceVersion = "evidence_version"
            case backgroundStatisticsVersion = "background_statistics_version"
            case runtimeStatus = "runtime_status"
            case eligibleForDefault = "eligible_for_default"
            case modelArrays = "model_arrays"
            case missingFieldPolicy = "missing_field_policy"
        }

        var isCandidate8ShadowContract: Bool {
            schema == "uk_wsr_candidate8_runtime_contract"
                && schemaVersion == 1
                && evidenceVersion == BackgroundModelRegistry.requiredQCVersion
                && backgroundStatisticsVersion == BackgroundModel.candidate8StatisticsVersion
                && runtimeStatus == "shadow_only"
                && !eligibleForDefault
                && Set(modelArrays) == Set([
                    "static_echo_date_sample_count",
                    "static_echo_date_frequency",
                    "static_echo_season_count",
                    "static_echo_time_bucket_count",
                    "static_dbzh_p10",
                    "static_dbzh_median",
                    "static_dbzh_p90",
                ])
                && missingFieldPolicy["missing_temporal_required"] == "abstain_keep"
                && missingFieldPolicy["missing_expected_upper_dbzh"] == "abstain_keep"
                && missingFieldPolicy["upper_dbzh_without_static_confirmation"] == "protect_keep"
        }
    }

    struct Entry: Decodable {
        var filename: String
        var status: String?
        var qcVersion: String?
        var eligibleForDefault: Bool?
        var qualificationReasons: [String]?

        enum CodingKeys: String, CodingKey {
            case filename
            case status
            case qcVersion = "qc_version"
            case eligibleForDefault = "eligible_for_default"
            case qualificationReasons = "qualification_reasons"
        }

        var isEligible: Bool {
            eligibleForDefault == true &&
                status == "qualified" &&
                qcVersion == BackgroundModelRegistry.requiredQCVersion &&
                (qualificationReasons ?? []).isEmpty
        }

        var isShadowEligible: Bool {
            ["quarantined", "qualified"].contains(status ?? "")
                && qcVersion == BackgroundModelRegistry.requiredQCVersion
        }
    }

    struct RegisteredModelURL: Hashable {
        var url: URL
        var eligibleForValidatedRuntime: Bool
    }

    static func load(from url: URL) throws -> BackgroundModelRegistry {
        try JSONDecoder().decode(BackgroundModelRegistry.self, from: Data(contentsOf: url))
    }

    func eligibleModelURLs(relativeTo directory: URL, fileManager: FileManager = .default) -> [URL] {
        registeredModelURLs(relativeTo: directory, fileManager: fileManager)
            .filter(\.eligibleForValidatedRuntime)
            .map(\.url)
    }

    func registeredModelURLs(
        relativeTo directory: URL,
        fileManager: FileManager = .default
    ) -> [RegisteredModelURL] {
        guard schema == Self.schemaName,
              schemaVersion >= Self.minimumSchemaVersion,
              runtimeStatus == "shadow_only",
              contractSHA256 == Self.requiredContractSHA256,
              contract?.isCandidate8ShadowContract == true else {
            return []
        }
        let root = directory.standardizedFileURL
        let rootPrefix = root.path.hasSuffix("/") ? root.path : root.path + "/"
        return models.compactMap { entry in
            guard entry.isShadowEligible, !entry.filename.isEmpty else {
                return nil
            }
            let candidate = root.appendingPathComponent(entry.filename).standardizedFileURL
            guard candidate.path.hasPrefix(rootPrefix),
                  fileManager.fileExists(atPath: candidate.path) else {
                return nil
            }
            return RegisteredModelURL(
                url: candidate,
                eligibleForValidatedRuntime: entry.isEligible
            )
        }
    }
}

struct PPIStats: Hashable {
    var validMin: Double?
    var validMax: Double?
    var scaleMin: Double?
    var scaleMax: Double?
}

struct PolarField {
    var values: [Float]
    var gateValues: [Float]?
    var gateQuantity: String?
    var companionFields: [String: [Float]]
    var rows: Int
    var columns: Int
    var metadata: RadarGridMetadata

    init(
        values: [Float],
        gateValues: [Float]? = nil,
        gateQuantity: String? = nil,
        companionFields: [String: [Float]] = [:],
        rows: Int,
        columns: Int,
        metadata: RadarGridMetadata
    ) {
        self.values = values
        self.gateValues = gateValues
        self.gateQuantity = gateQuantity
        var normalizedCompanions = [String: [Float]]()
        for (quantity, values) in companionFields {
            normalizedCompanions[normalizedQuantityKey(quantity)] = values
        }
        if let gateValues, let gateQuantity {
            normalizedCompanions[normalizedQuantityKey(gateQuantity)] = gateValues
        }
        self.companionFields = normalizedCompanions
        self.rows = rows
        self.columns = columns
        self.metadata = metadata
    }
}

/// Independently observed fields required for Candidate 8 learned-clutter removal.
/// The renderer treats an incomplete or misaligned context as unavailable and preserves
/// the current scan rather than guessing from the learned background.
struct Candidate8Context: Hashable {
    var previousDBZH: [Float]?
    var nextDBZH: [Float]?
    var previousVRAD: [Float]?
    var nextVRAD: [Float]?
    var upperElevationDBZH: [Float]?
    var upperElevationVRAD: [Float]? = nil
    var upperElevationSQI: [Float]? = nil
    var upperElevationRHOHV: [Float]? = nil
    var upperElevationZDR: [Float]? = nil
    var upperElevationPHIDP: [Float]? = nil
    var upperElevationWidth: [Float]? = nil
    var upperElevationRequired: Bool

    func isComplete(valueCount: Int) -> Bool {
        let required = [previousDBZH, nextDBZH, previousVRAD, nextVRAD]
        guard required.allSatisfy({ $0?.count == valueCount }) else {
            return false
        }
        return !upperElevationRequired || upperElevationDBZH?.count == valueCount
    }
}

struct PPIFrame: Identifiable, Hashable {
    let id = UUID()
    var metadata: RadarGridMetadata
    var dataFingerprint: String
    var sourceShape: [Int]
    var rows: Int
    var columns: Int
    var rowStride: Int
    var columnStride: Int
    var scaled: [UInt8]
    var valid: [Bool]
    var filteredValues: [Float]
    var originalValues: [Float]
    var stats: PPIStats
    var palette: String
    var requestedPalette: String
    var maskBelowMin: Bool
    var noiseFloor: NoiseFloorResult
    var backgroundModel: BackgroundModelResult
    var qcV3: QCV3RuntimeResult

    func index(row: Int, column: Int) -> Int {
        max(0, min(rows - 1, row)) * columns + max(0, min(columns - 1, column))
    }
}

struct IdentifyResult: Hashable {
    var row: Int
    var column: Int
    var quantity: String
    var value: Double?
    var originalValue: Double?
    var maskedByNoiseFloor: Bool
    var rangeM: Double
    var rangeKm: Double
    var azimuthDeg: Double
    var longitude: Double
    var latitude: Double
    var elevationDeg: Double?
    var beamHeightM: Double?

    var compactDescription: String {
        return "\(valueDescription)  \(String(format: "%.1f", rangeKm)) km  \(String(format: "%.1f°", azimuthDeg))"
    }

    var detailedDescription: String {
        return [
            valueDescription,
            "range=\(rangeText)",
            "az=\(azimuthText)",
            "height=\(heightText)",
            "elev=\(elevationText)",
            "lat/lon=\(coordinateText)",
            "row=\(row)",
            "col=\(column)",
        ].joined(separator: ", ")
    }

    var valueDescription: String {
        if maskedByNoiseFloor {
            return "\(quantity)=masked"
        }
        guard let value else {
            return "\(quantity)=no data"
        }
        let unit = quantityUnit(quantity)
        let formatted = String(format: abs(value) >= 100 ? "%.1f" : "%.2f", value)
        return unit.isEmpty ? "\(quantity)=\(formatted)" : "\(quantity)=\(formatted) \(unit)"
    }

    var rawValueText: String {
        guard let originalValue else { return "n/a" }
        let unit = quantityUnit(quantity)
        let formatted = String(format: abs(originalValue) >= 100 ? "%.1f" : "%.2f", originalValue)
        return unit.isEmpty ? formatted : "\(formatted) \(unit)"
    }

    var valueStatusText: String {
        if maskedByNoiseFloor {
            return "Masked by cleanup"
        }
        return value == nil ? "No data" : "Valid gate"
    }

    var rangeText: String {
        String(format: "%.2f km", rangeKm)
    }

    var azimuthText: String {
        String(format: "%.1f°", azimuthDeg)
    }

    var heightText: String {
        beamHeightM.map { String(format: "%.2f km", $0 / 1000) } ?? "n/a"
    }

    var elevationText: String {
        elevationDeg.map { String(format: "%.2f°", $0) } ?? "n/a"
    }

    var coordinateText: String {
        String(format: "%.5f, %.5f", latitude, longitude)
    }

    var binText: String {
        "\(row), \(column)"
    }
}

struct DisplayConfig {
    var palette: String
    var scaleMin: Double?
    var scaleMax: Double?
    var maskBelowMin: Bool

    static func forQuantity(_ quantity: String, requestedPalette: String) -> DisplayConfig {
        let upper = quantity.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let lower = quantity.lowercased()
        var palette = ["", "auto", "standard"].contains(requestedPalette.lowercased()) ? "" : requestedPalette
        var limits: (Double?, Double?) = (nil, nil)
        var maskBelowMin = false

        if isReflectivityQuantity(upper) || lower.contains("reflectivity") {
            palette = palette.isEmpty ? "homeyer" : palette
            limits = (-30, 60)
            maskBelowMin = true
        } else if ["VRAD", "VRADH", "VRADDH", "VRADV", "VEL", "VELH", "VELV", "V"].contains(upper) || lower.contains("velocity") {
            palette = palette.isEmpty ? "BuDRd18" : palette
            limits = (-30, 30)
        } else if ["WRAD", "WRADH", "WRADV", "WIDTH", "SW", "SWRAD"].contains(upper) || lower.contains("spectrum_width") {
            palette = palette.isEmpty ? "NWS_SPW" : palette
            limits = (0, 10)
        } else if ["ZDR", "ZDRH", "ZDRV"].contains(upper) || lower.contains("differential_reflectivity") {
            palette = palette.isEmpty ? "RefDiff" : palette
            limits = (-1, 8)
        } else if ["RHOHV", "RHO", "CC", "SQIH"].contains(upper) || lower.contains("cross_correlation") {
            palette = palette.isEmpty ? "RefDiff" : palette
            limits = (0.5, 1.05)
        } else if ["PHIDP", "UPHIDP", "PHI"].contains(upper) || lower.contains("differential_phase") {
            palette = palette.isEmpty ? "Wild25" : palette
            limits = (-180, 180)
        } else if ["KDP", "KDPH", "KDPV"].contains(upper) || lower.contains("specific_differential_phase") {
            palette = palette.isEmpty ? "Theodore16" : palette
            limits = (-2, 5)
        } else if ["RATE", "RRATE", "RATE_H", "RATE_Z", "R"].contains(upper) || lower.contains("rain_rate") {
            palette = palette.isEmpty ? "RRate11" : palette
            limits = (0, 50)
        } else if ["SNR", "SNRH", "SNRV"].contains(upper) || lower.contains("signal_to_noise") {
            palette = palette.isEmpty ? "Carbone17" : palette
            limits = (-20, 30)
        } else {
            palette = palette.isEmpty ? "gray" : palette
        }

        return DisplayConfig(palette: palette, scaleMin: limits.0, scaleMax: limits.1, maskBelowMin: maskBelowMin)
    }
}

func isReflectivityQuantity(_ quantity: String) -> Bool {
    let upper = quantity.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
    let lower = quantity.lowercased()
    return ["DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"].contains(upper)
        || lower.contains("reflectivity")
}

func normalizedQuantityKey(_ quantity: String) -> String {
    quantity.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
}

func quantityUnit(_ quantity: String) -> String {
    let key = normalizedQuantityKey(quantity)
    if ["DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"].contains(key) {
        return "dBZ"
    }
    if ["ZDR", "ZDRH", "ZDRV"].contains(key) {
        return "dB"
    }
    if ["VRAD", "VRADH", "VRADDH", "VRADV", "VEL", "VELH", "VELV", "V", "WRAD", "WRADH", "WRADV", "WIDTH", "SW", "SWRAD"].contains(key) {
        return "m/s"
    }
    if ["PHIDP", "UPHIDP", "PHI"].contains(key) {
        return "deg"
    }
    if ["KDP", "KDPH", "KDPV"].contains(key) {
        return "deg/km"
    }
    if ["RHOHV", "RHO", "CC", "SQIH", "SQI", "QIND", "CI"].contains(key) {
        return ""
    }
    if ["RATE", "RRATE", "RATE_H", "RATE_Z", "R"].contains(key) {
        return "mm/h"
    }
    if ["SNR", "SNRH", "SNRV"].contains(key) {
        return "dB"
    }
    return ""
}

struct RGBAColor: Hashable {
    var red: Double
    var green: Double
    var blue: Double
    var alpha: Double = 1

    var color: Color {
        Color(red: red / 255, green: green / 255, blue: blue / 255, opacity: alpha)
    }
}

enum PaletteEngine {
    static let paletteNames = ["auto", "homeyer", "BuDRd18", "RefDiff", "NWS_SPW", "Wild25", "Theodore16", "RRate11", "Carbone17", "gray", "radar", "thermal", "velocity"]

    static func displayName(for palette: String) -> String {
        switch palette.lowercased() {
        case "auto":
            return "Auto by variable"
        case "homeyer":
            return "Homeyer DBZ"
        case "budrd18":
            return "Velocity BuDRd"
        case "refdiff":
            return "Difference RefDiff"
        case "nws_spw":
            return "Spectrum width"
        case "wild25":
            return "Phase Wild"
        case "theodore16":
            return "KDP Theodore"
        case "rrate11":
            return "Rain rate"
        case "carbone17":
            return "Signal/noise"
        case "gray", "grey":
            return "Gray"
        case "radar":
            return "Radar"
        case "thermal":
            return "Thermal"
        case "velocity":
            return "Velocity"
        default:
            return palette
        }
    }

    static func color(_ scaled: UInt8, palette: String, opacity: Double = 1) -> Color {
        var rgba = rgbaColor(scaled, palette: palette)
        rgba.alpha = opacity
        return rgba.color
    }

    static func rgba(_ scaled: UInt8, palette: String, opacity: Double = 1) -> RGBAColor {
        var rgba = rgbaColor(scaled, palette: palette)
        rgba.alpha = opacity
        return rgba
    }

    private static func rgbaColor(_ scaled: UInt8, palette: String) -> RGBAColor {
        let value = Double(scaled)
        switch palette.lowercased() {
        case "gray", "grey":
            return RGBAColor(red: value, green: value, blue: value)
        case "radar":
            return RGBAColor(
                red: clamp(value * 2 - 120, 0, 255),
                green: clamp(value * 2, 0, 255),
                blue: clamp(180 - value * 2, 0, 255)
            )
        case "thermal":
            return RGBAColor(
                red: value,
                green: clamp(value * 1.35 - 75, 0, 255),
                blue: clamp(255 - value * 1.2, 0, 255)
            )
        case "velocity":
            return RGBAColor(
                red: clamp(value * 2 - 255, 0, 255),
                green: clamp(255 - abs(value - 128) * 2, 0, 255),
                blue: clamp(255 - value * 2, 0, 255)
            )
        case "homeyer":
            return stopColor(value, stops: [
                (0.00, (245, 245, 245)), (0.08, (120, 200, 255)), (0.18, (20, 80, 220)),
                (0.30, (25, 170, 60)), (0.43, (250, 230, 30)), (0.56, (245, 125, 20)),
                (0.68, (210, 25, 35)), (0.80, (185, 35, 160)), (0.91, (250, 250, 250)),
                (1.00, (120, 70, 40))
            ])
        case "budrd18":
            return stopColor(value, stops: [
                (0.00, (5, 48, 97)), (0.18, (33, 102, 172)), (0.34, (146, 197, 222)),
                (0.50, (247, 247, 247)), (0.66, (244, 165, 130)), (0.82, (178, 24, 43)),
                (1.00, (103, 0, 31))
            ])
        case "refdiff":
            return stopColor(value, stops: [
                (0.00, (49, 54, 149)), (0.20, (69, 117, 180)), (0.40, (171, 217, 233)),
                (0.50, (255, 255, 191)), (0.60, (254, 224, 144)), (0.80, (244, 109, 67)),
                (1.00, (165, 0, 38))
            ])
        case "nws_spw":
            return stopColor(value, stops: [
                (0.00, (255, 255, 255)), (0.15, (153, 204, 255)), (0.30, (76, 153, 255)),
                (0.45, (76, 204, 76)), (0.60, (255, 230, 0)), (0.78, (255, 128, 0)),
                (1.00, (180, 0, 0))
            ])
        case "wild25":
            return stopColor(value, stops: [
                (0.00, (68, 1, 84)), (0.18, (59, 82, 139)), (0.34, (33, 145, 140)),
                (0.50, (94, 201, 98)), (0.66, (253, 231, 37)), (0.82, (241, 135, 33)),
                (1.00, (180, 40, 120))
            ])
        case "theodore16":
            return stopColor(value, stops: [
                (0.00, (49, 54, 149)), (0.20, (69, 117, 180)), (0.40, (116, 173, 209)),
                (0.50, (255, 255, 191)), (0.64, (254, 224, 144)), (0.80, (244, 109, 67)),
                (1.00, (165, 0, 38))
            ])
        case "rrate11":
            return stopColor(value, stops: [
                (0.00, (247, 252, 245)), (0.14, (199, 233, 192)), (0.28, (116, 196, 118)),
                (0.42, (49, 163, 84)), (0.58, (254, 224, 144)), (0.74, (253, 141, 60)),
                (1.00, (189, 0, 38))
            ])
        case "carbone17":
            return stopColor(value, stops: [
                (0.00, (38, 38, 38)), (0.18, (88, 88, 88)), (0.36, (150, 150, 150)),
                (0.52, (210, 210, 210)), (0.68, (150, 200, 255)), (0.84, (60, 140, 220)),
                (1.00, (10, 65, 140))
            ])
        default:
            return RGBAColor(
                red: clamp(value * 2 - 120, 0, 255),
                green: clamp(value * 2, 0, 255),
                blue: clamp(180 - value * 2, 0, 255)
            )
        }
    }

    private static func stopColor(_ scaled: Double, stops: [(Double, (Double, Double, Double))]) -> RGBAColor {
        let position = clamp(scaled / 255, 0, 1)
        guard let first = stops.first else { return RGBAColor(red: scaled, green: scaled, blue: scaled) }
        var previous = first
        for stop in stops.dropFirst() {
            if position <= stop.0 {
                let span = max(stop.0 - previous.0, 0.0001)
                let t = clamp((position - previous.0) / span, 0, 1)
                return RGBAColor(
                    red: previous.1.0 + (stop.1.0 - previous.1.0) * t,
                    green: previous.1.1 + (stop.1.1 - previous.1.1) * t,
                    blue: previous.1.2 + (stop.1.2 - previous.1.2) * t
                )
            }
            previous = stop
        }
        return RGBAColor(red: previous.1.0, green: previous.1.1, blue: previous.1.2)
    }
}

protocol RadarVolumeReader {
    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord]
    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField
}

extension RadarVolumeReader {
    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        []
    }
}

struct NativeHDF5VolumeReader: RadarVolumeReader {
    private static let suppressionCompanionCandidates = [
        "DBZH",
        "CI",
        "SQIH",
        "RHOHV",
        "ZDR",
        "PHIDP", "UPHIDP",
        "VRADH",
        "WRADH",
        "LONG_RANGE_NOISE_DBC_H",
        "LONG_RANGE_NOISE_DBC_V",
    ]

    private struct DecodedPolarSource {
        var values: [Float]
        var rows: Int
        var columns: Int
        var dataset: String
        var quantity: String
        var latitude: Double
        var longitude: Double
        var heightM: Double?
        var elevationDeg: Double?
        var rstartKm: Double
        var rscaleM: Double
    }

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        if fileURL.pathExtension.lowercased() == "json" {
            return try JSONPolarFixtureReader().inspectFields(from: fileURL, item: item, pulse: pulse, time: time)
        }

        var records = [UKHDF5FieldRecord](repeating: UKHDF5FieldRecord(), count: 512)
        var recordCount: Int32 = 0
        var errorBuffer = [CChar](repeating: 0, count: 512)
        let didInspect = fileURL.withUnsafeFileSystemRepresentation { pathPointer -> Int32 in
            guard let pathPointer else { return 0 }
            return records.withUnsafeMutableBufferPointer { buffer in
                UKHDF5InspectODIMFields(
                    pathPointer,
                    buffer.baseAddress,
                    Int32(buffer.count),
                    &recordCount,
                    &errorBuffer,
                    errorBuffer.count
                )
            }
        }

        guard didInspect != 0 else {
            throw RadarAppError.hdf5ReadFailed(String(cString: errorBuffer))
        }

        return records.prefix(Int(recordCount)).map { record in
            let datasetName = fixedCString(record.datasetName)
            let dataset = datasetName.hasPrefix("dataset") ? String(datasetName.dropFirst("dataset".count)) : datasetName
            let shape = [Int(record.rows), Int(record.columns)].filter { $0 > 0 }
            return QuantityRecord(
                pulse: pulse,
                time: time,
                dataset: dataset,
                kind: "data",
                index: String(record.dataIndex),
                quantity: fixedCString(record.quantity),
                shape: shape,
                dtype: "",
                elevationDeg: record.elevationDeg.isFinite ? record.elevationDeg : nil
            )
        }
    }

    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        if fileURL.pathExtension.lowercased() == "json" {
            return try JSONPolarFixtureReader().readPolarField(from: fileURL, item: item, selection: selection)
        }

        let requestedDataset = selection.dataset ?? ""
        let decoded = try readCPolarField(from: fileURL, dataset: requestedDataset, quantity: selection.quantity)
        let decodedDataset = decoded.dataset
        let decodedQuantity = decoded.quantity.isEmpty ? selection.quantity : decoded.quantity
        let companionFields = suppressionCompanionFields(
            from: fileURL,
            dataset: decodedDataset.isEmpty ? requestedDataset : decodedDataset,
            selected: decoded
        )
        let gateSource = reflectivityGateSource(
            selected: decoded,
            selectedQuantity: decodedQuantity,
            companionFields: companionFields
        )
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: decodedQuantity,
            dataset: decodedDataset.isEmpty ? selection.dataset ?? "auto" : decodedDataset,
            latitude: decoded.latitude,
            longitude: decoded.longitude,
            heightM: decoded.heightM,
            elevationDeg: decoded.elevationDeg,
            rstartKm: decoded.rstartKm,
            rscaleM: decoded.rscaleM,
            nbins: decoded.columns,
            nrays: decoded.rows
        )

        return PolarField(
            values: decoded.values,
            gateValues: gateSource?.values,
            gateQuantity: gateSource?.quantity,
            companionFields: companionFields,
            rows: decoded.rows,
            columns: decoded.columns,
            metadata: metadata
        )
    }

    private func readCPolarField(from fileURL: URL, dataset: String, quantity: String) throws -> DecodedPolarSource {
        var cField = UKHDF5PolarField()
        var errorBuffer = [CChar](repeating: 0, count: 512)

        let didRead = fileURL.withUnsafeFileSystemRepresentation { pathPointer -> Int32 in
            guard let pathPointer else { return 0 }
            return dataset.withCString { datasetPointer in
                quantity.withCString { quantityPointer in
                    UKHDF5ReadODIMField(
                        pathPointer,
                        datasetPointer,
                        quantityPointer,
                        &cField,
                        &errorBuffer,
                        errorBuffer.count
                    )
                }
            }
        }

        guard didRead != 0 else {
            throw RadarAppError.hdf5ReadFailed(String(cString: errorBuffer))
        }

        defer { UKHDF5FreePolarField(&cField) }

        let rows = Int(cField.rows)
        let columns = Int(cField.columns)
        let valueCount = Int(cField.valueCount)
        guard rows > 0, columns > 0, valueCount == rows * columns, let valuesPointer = cField.values else {
            throw RadarAppError.hdf5ReadFailed("The decoded HDF5 field had an invalid shape.")
        }

        let values = Array(UnsafeBufferPointer(start: valuesPointer, count: valueCount))
        return DecodedPolarSource(
            values: values,
            rows: rows,
            columns: columns,
            dataset: fixedCString(cField.datasetName),
            quantity: fixedCString(cField.quantity),
            latitude: cField.latitude.isFinite ? cField.latitude : 0,
            longitude: cField.longitude.isFinite ? cField.longitude : 0,
            heightM: cField.heightM.isFinite ? cField.heightM : nil,
            elevationDeg: cField.elevationDeg.isFinite ? cField.elevationDeg : nil,
            rstartKm: cField.rstartKm.isFinite ? cField.rstartKm : 0,
            rscaleM: cField.rscaleM.isFinite ? cField.rscaleM : 1000
        )
    }

    private func suppressionCompanionFields(
        from fileURL: URL,
        dataset: String,
        selected: DecodedPolarSource
    ) -> [String: [Float]] {
        var fields = [normalizedQuantityKey(selected.quantity): selected.values]
        for quantity in Self.suppressionCompanionCandidates {
            let key = normalizedQuantityKey(quantity)
            if fields[key] != nil {
                continue
            }
            guard let source = try? readCPolarField(from: fileURL, dataset: dataset, quantity: quantity),
                  source.rows == selected.rows,
                  let values = broadcastCompanionValues(source, columns: selected.columns) else {
                continue
            }
            fields[normalizedQuantityKey(source.quantity.isEmpty ? quantity : source.quantity)] = values
        }
        return fields
    }

    private func broadcastCompanionValues(_ source: DecodedPolarSource, columns: Int) -> [Float]? {
        if source.columns == columns {
            return source.values
        }
        guard source.columns == 1, columns > 0, source.values.count == source.rows else {
            return nil
        }
        var expanded = [Float]()
        expanded.reserveCapacity(source.rows * columns)
        for value in source.values {
            expanded.append(contentsOf: repeatElement(value, count: columns))
        }
        return expanded
    }

    private func reflectivityGateSource(
        selected: DecodedPolarSource,
        selectedQuantity: String,
        companionFields: [String: [Float]]
    ) -> (values: [Float], quantity: String)? {
        if isReflectivityQuantity(selectedQuantity) {
            return (selected.values, selectedQuantity)
        }

        for quantity in ["DBZH", "TH", "DBZ", "DBZV", "DBZHC", "DBZVC", "CZ", "DZ", "AZ", "Z"] {
            if let values = companionFields[normalizedQuantityKey(quantity)] {
                return (values, quantity)
            }
        }
        return nil
    }

    private func fixedCString<T>(_ tuple: T) -> String {
        withUnsafeBytes(of: tuple) { bytes in
            guard let baseAddress = bytes.baseAddress else { return "" }
            return String(cString: baseAddress.assumingMemoryBound(to: CChar.self))
        }
    }
}

struct JSONPolarFixtureReader: RadarVolumeReader {
    private struct Fixture: Codable {
        var values: [[Double?]]
        var metadata: FixtureMetadata
    }

    private struct FixtureMetadata: Codable {
        var latitude: Double
        var longitude: Double
        var heightM: Double?
        var elevationDeg: Double?
        var rstartKm: Double
        var rscaleM: Double

        enum CodingKeys: String, CodingKey {
            case latitude
            case longitude
            case heightM = "height_m"
            case elevationDeg = "elevation_deg"
            case rstartKm = "rstart_km"
            case rscaleM = "rscale_m"
        }
    }

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: fileURL))
        return [QuantityRecord(
            pulse: pulse,
            time: time,
            dataset: "1",
            kind: "data",
            index: "1",
            quantity: "DBZH",
            shape: [fixture.values.count, fixture.values.first?.count ?? 0].filter { $0 > 0 },
            dtype: "float32",
            elevationDeg: fixture.metadata.elevationDeg
        )]
    }

    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: fileURL))
        let rows = fixture.values.count
        let columns = fixture.values.first?.count ?? 0
        guard rows > 0, columns > 0 else {
            throw RadarAppError.unsupportedFixture(fileURL.lastPathComponent)
        }
        let values = fixture.values.flatMap { row in
            row.map { value in value.map(Float.init) ?? Float.nan }
        }
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: selection.quantity,
            dataset: selection.dataset.map { $0.hasPrefix("dataset") ? $0 : "dataset\($0)" } ?? "auto",
            latitude: fixture.metadata.latitude,
            longitude: fixture.metadata.longitude,
            heightM: fixture.metadata.heightM,
            elevationDeg: fixture.metadata.elevationDeg,
            rstartKm: fixture.metadata.rstartKm,
            rscaleM: fixture.metadata.rscaleM,
            nbins: columns,
            nrays: rows
        )
        return PolarField(
            values: values,
            gateValues: isReflectivityQuantity(selection.quantity) ? values : nil,
            gateQuantity: isReflectivityQuantity(selection.quantity) ? selection.quantity : nil,
            companionFields: isReflectivityQuantity(selection.quantity) ? [selection.quantity: values] : [:],
            rows: rows,
            columns: columns,
            metadata: metadata
        )
    }
}

struct RadarRenderer {
    func render(
        field: PolarField,
        filters: RadarFilterSet,
        backgroundModel: BackgroundModel? = nil,
        candidate8Context: Candidate8Context? = nil,
        maxRays: Int = 1440,
        maxBins: Int = 1200
    ) -> PPIFrame {
        var filtered = applyBasicFilters(values: field.values, rows: field.rows, columns: field.columns, metadata: field.metadata, filters: filters)
        let gateQuantity = field.gateQuantity ?? (isReflectivityQuantity(field.metadata.quantity) ? field.metadata.quantity : nil)
        let gateValues = field.gateValues ?? (isReflectivityQuantity(field.metadata.quantity) ? field.values : nil)
        var companionFields = field.companionFields
        if let gateValues, let gateQuantity {
            companionFields[normalizedQuantityKey(gateQuantity)] = gateValues
        }
        let spatialCompanionFields = companionFields.mapValues {
            applySpatialFilters(values: $0, rows: field.rows, columns: field.columns, metadata: field.metadata, filters: filters)
        }
        let spatialGateValues = gateValues.map {
            applySpatialFilters(values: $0, rows: field.rows, columns: field.columns, metadata: field.metadata, filters: filters)
        }
        let sourceDescription = suppressionSourceDescription(gateQuantity: gateQuantity, companionFields: spatialCompanionFields)
        let safeInput = filtered
        let noise = applyNoiseFloor(
            values: &filtered,
            gateValues: spatialGateValues,
            sourceDescription: sourceDescription,
            companionFields: spatialCompanionFields,
            rows: field.rows,
            columns: field.columns,
            filters: filters
        )
        let safeMask = zip(safeInput, filtered).map {
            $0.0.isFinite && !$0.1.isFinite
        }
        var proposedMask = safeMask
        var learnedCandidateApplied = false
        var bundleQualification = "safe_baseline"
        let background: BackgroundModelResult
        switch filters.qcRuntimeMode {
        case .safe:
            background = BackgroundModelResult(
                enabled: filters.backgroundModelEnabled,
                applied: false,
                finiteBefore: filtered.filter(\.isFinite).count,
                finiteAfter: filtered.filter(\.isFinite).count,
                reason: filters.backgroundModelEnabled ? "safe_mode_shadow_required" : nil
            )
        case .shadow:
            var shadowValues = filtered
            let shadowEvaluation = applyBackgroundModel(
                values: &shadowValues,
                gateValues: spatialGateValues,
                companionFields: spatialCompanionFields,
                metadata: field.metadata,
                gateQuantity: gateQuantity,
                rows: field.rows,
                columns: field.columns,
                filters: filters,
                model: backgroundModel,
                candidate8Context: candidate8Context
            )
            background = BackgroundModelResult(
                enabled: shadowEvaluation.enabled,
                applied: false,
                modelKey: shadowEvaluation.modelKey,
                maskedCount: shadowEvaluation.maskedCount,
                finiteBefore: shadowEvaluation.finiteBefore,
                finiteAfter: shadowEvaluation.finiteBefore,
                reason: shadowEvaluation.applied ? "shadow_only" : shadowEvaluation.reason
            )
            proposedMask = zip(filtered, shadowValues).enumerated().map {
                safeMask[$0.offset] || ($0.element.0.isFinite && !$0.element.1.isFinite)
            }
            bundleQualification = "shadow_only"
        case .validated:
            guard filters.qcValidatedBundleID != nil else {
                background = BackgroundModelResult(
                    enabled: filters.backgroundModelEnabled,
                    applied: false,
                    finiteBefore: filtered.filter(\.isFinite).count,
                    finiteAfter: filtered.filter(\.isFinite).count,
                    reason: "missing_validated_bundle"
                )
                bundleQualification = "missing_validated_bundle"
                break
            }
            background = applyBackgroundModel(
                values: &filtered,
                gateValues: spatialGateValues,
                companionFields: spatialCompanionFields,
                metadata: field.metadata,
                gateQuantity: gateQuantity,
                rows: field.rows,
                columns: field.columns,
                filters: filters,
                model: backgroundModel,
                candidate8Context: candidate8Context
            )
            proposedMask = zip(safeInput, filtered).map {
                $0.0.isFinite && !$0.1.isFinite
            }
            learnedCandidateApplied = background.applied
            bundleQualification = "validated:\(filters.qcValidatedBundleID ?? "")"
        }
        var reasonFlags = Array(repeating: UInt16(0), count: filtered.count)
        for index in reasonFlags.indices where safeMask[index] {
            reasonFlags[index] |= QCV3ReasonFlag.receiverNoise.rawValue
        }
        for index in reasonFlags.indices where proposedMask[index] && !safeMask[index] {
            reasonFlags[index] |= QCV3ReasonFlag.persistentGroundClutter.rawValue
        }
        let removalMask = zip(safeInput, filtered).map {
            $0.0.isFinite && !$0.1.isFinite
        }
        let qcV3 = QCV3RuntimeResult(
            mode: filters.qcRuntimeMode,
            removalMask: removalMask,
            proposedRemovalMask: proposedMask,
            abstentionMask: zip(proposedMask, removalMask).map {
                $0.0 && !$0.1
            },
            reasonFlags: reasonFlags,
            learnedCandidateApplied: learnedCandidateApplied,
            bundleQualification: bundleQualification
        )
        let rowStride = max(1, Int(ceil(Double(field.rows) / Double(max(24, min(maxRays, 1440))))))
        let columnStride = max(1, Int(ceil(Double(field.columns) / Double(max(24, min(maxBins, 1200))))))
        let sampledRows = Int(ceil(Double(field.rows) / Double(rowStride)))
        let sampledColumns = Int(ceil(Double(field.columns) / Double(columnStride)))
        var sampled = [Float]()
        var original = [Float]()
        sampled.reserveCapacity(sampledRows * sampledColumns)
        original.reserveCapacity(sampledRows * sampledColumns)

        var sourceRow = 0
        while sourceRow < field.rows {
            var sourceColumn = 0
            while sourceColumn < field.columns {
                let index = sourceRow * field.columns + sourceColumn
                sampled.append(filtered[index])
                original.append(field.values[index])
                sourceColumn += columnStride
            }
            sourceRow += rowStride
        }

        let display = DisplayConfig.forQuantity(field.metadata.quantity, requestedPalette: filters.palette)
        let limits = displayLimits(filters: filters, display: display)
        let scaling = scale(values: sampled, scaleMin: limits.min, scaleMax: limits.max, maskBelowMin: limits.maskBelowMin)

        return PPIFrame(
            metadata: field.metadata,
            dataFingerprint: dataFingerprint(values: original, valid: scaling.valid),
            sourceShape: [field.rows, field.columns],
            rows: sampledRows,
            columns: sampledColumns,
            rowStride: rowStride,
            columnStride: columnStride,
            scaled: scaling.scaled,
            valid: scaling.valid,
            filteredValues: sampled,
            originalValues: original,
            stats: scaling.stats,
            palette: display.palette,
            requestedPalette: filters.palette,
            maskBelowMin: display.maskBelowMin,
            noiseFloor: noise,
            backgroundModel: background,
            qcV3: qcV3
        )
    }

    private func displayLimits(
        filters: RadarFilterSet,
        display: DisplayConfig
    ) -> (min: Double?, max: Double?, maskBelowMin: Bool) {
        switch filters.displayRangeMode {
        case .standard:
            return (display.scaleMin, display.scaleMax, display.maskBelowMin)
        case .dataStretch:
            return (nil, nil, false)
        case .custom:
            return (
                filters.displayMin ?? display.scaleMin,
                filters.displayMax ?? display.scaleMax,
                display.maskBelowMin
            )
        }
    }

    private func dataFingerprint(values: [Float], valid: [Bool]) -> String {
        var hash: UInt64 = 0xcbf29ce484222325

        func mix(_ byte: UInt8) {
            hash ^= UInt64(byte)
            hash &*= 0x100000001b3
        }

        for value in values {
            let bits = value.bitPattern
            mix(UInt8(truncatingIfNeeded: bits))
            mix(UInt8(truncatingIfNeeded: bits >> 8))
            mix(UInt8(truncatingIfNeeded: bits >> 16))
            mix(UInt8(truncatingIfNeeded: bits >> 24))
        }

        for flag in valid {
            mix(flag ? 1 : 0)
        }

        let hex = String(hash, radix: 16, uppercase: false)
        let padded = String(repeating: "0", count: max(0, 16 - hex.count)) + hex
        return String(padded.prefix(8))
    }

    func identify(frame: PPIFrame, row: Int, column: Int) -> IdentifyResult {
        let clippedRow = max(0, min(frame.rows - 1, row))
        let clippedColumn = max(0, min(frame.columns - 1, column))
        let index = frame.index(row: clippedRow, column: clippedColumn)
        let value = finiteDouble(frame.filteredValues[index])
        let original = finiteDouble(frame.originalValues[index])
        let sourceRow = clippedRow * frame.rowStride
        let sourceColumn = clippedColumn * frame.columnStride
        let rangeM = frame.metadata.rstartKm * 1000 + (Double(sourceColumn) + 0.5) * frame.metadata.rscaleM
        let azimuthDeg = ((Double(sourceRow) + 0.5) / Double(max(frame.metadata.nrays, 1))) * 360
        let azimuthRad = azimuthDeg * Double.pi / 180
        let x = rangeM * sin(azimuthRad)
        let y = rangeM * cos(azimuthRad)
        let point = geographicPoint(metadata: frame.metadata, xM: x, yM: y)
        return IdentifyResult(
            row: clippedRow,
            column: clippedColumn,
            quantity: frame.metadata.quantity,
            value: value,
            originalValue: original,
            maskedByNoiseFloor: original != nil && value == nil,
            rangeM: rangeM,
            rangeKm: rangeM / 1000,
            azimuthDeg: azimuthDeg,
            longitude: point.longitude,
            latitude: point.latitude,
            elevationDeg: frame.metadata.elevationDeg,
            beamHeightM: beamHeightM(
                rangeM: rangeM,
                elevationDeg: frame.metadata.elevationDeg,
                siteHeightM: frame.metadata.heightM
            )
        )
    }

    private func beamHeightM(rangeM: Double, elevationDeg: Double?, siteHeightM: Double?) -> Double? {
        guard rangeM.isFinite, let elevationDeg, elevationDeg.isFinite else {
            return nil
        }
        let effectiveEarthRadiusM = (4.0 / 3.0) * 6_371_000.0
        let theta = elevationDeg * Double.pi / 180
        let height = sqrt(
            rangeM * rangeM +
                effectiveEarthRadiusM * effectiveEarthRadiusM +
                2 * rangeM * effectiveEarthRadiusM * sin(theta)
        ) - effectiveEarthRadiusM + (siteHeightM ?? 0)
        return height.isFinite ? height : nil
    }

    private func applyBasicFilters(values: [Float], rows: Int, columns: Int, metadata: RadarGridMetadata, filters: RadarFilterSet) -> [Float] {
        applyFilters(values: values, rows: rows, columns: columns, metadata: metadata, filters: filters, includeValueLimits: true)
    }

    private func applySpatialFilters(values: [Float], rows: Int, columns: Int, metadata: RadarGridMetadata, filters: RadarFilterSet) -> [Float] {
        applyFilters(values: values, rows: rows, columns: columns, metadata: metadata, filters: filters, includeValueLimits: false)
    }

    private func applyFilters(values: [Float], rows: Int, columns: Int, metadata: RadarGridMetadata, filters: RadarFilterSet, includeValueLimits: Bool) -> [Float] {
        var output = values
        for row in 0..<rows {
            let azimuth = ((Double(row) + 0.5) / Double(max(rows, 1))) * 360
            for column in 0..<columns {
                let index = row * columns + column
                guard output[index].isFinite else { continue }
                let rangeKm = (metadata.rstartKm * 1000 + (Double(column) + 0.5) * metadata.rscaleM) / 1000
                if let minRange = filters.minRangeKm, rangeKm < minRange { output[index] = Float.nan; continue }
                if let maxRange = filters.maxRangeKm, rangeKm > maxRange { output[index] = Float.nan; continue }
                if !azimuthAllowed(azimuth, min: filters.minAzimuthDeg, max: filters.maxAzimuthDeg) { output[index] = Float.nan; continue }
                guard includeValueLimits else { continue }
                if let minValue = filters.minValue, Double(output[index]) < minValue { output[index] = Float.nan; continue }
                if let maxValue = filters.maxValue, Double(output[index]) > maxValue { output[index] = Float.nan }
            }
        }
        return output
    }

    private func azimuthAllowed(_ value: Double, min: Double?, max: Double?) -> Bool {
        guard min != nil || max != nil else { return true }
        let lower = (min ?? 0).truncatingRemainder(dividingBy: 360)
        let upper = (max ?? 360).truncatingRemainder(dividingBy: 360)
        let azimuth = value.truncatingRemainder(dividingBy: 360)
        if lower <= upper {
            return azimuth >= lower && azimuth <= upper
        }
        return azimuth >= lower || azimuth <= upper
    }

    private func applyNoiseFloor(
        values: inout [Float],
        gateValues: [Float]?,
        sourceDescription: String?,
        companionFields: [String: [Float]],
        rows: Int,
        columns: Int,
        filters: RadarFilterSet
    ) -> NoiseFloorResult {
        let finiteBefore = values.filter(\.isFinite).count
        guard filters.noiseFloorEnabled else {
            return NoiseFloorResult(enabled: false, finiteBefore: finiteBefore, finiteAfter: finiteBefore)
        }
        guard let gateValues, gateValues.count == values.count, gateValues.contains(where: \.isFinite) else {
            return NoiseFloorResult(enabled: false, finiteBefore: finiteBefore, finiteAfter: finiteBefore)
        }

        let method = filters.noiseFloorMethod == "estimated" ? "estimated" : "estimated"
        let operation = filters.noiseFloorOperation == "mask" ? "mask" : "mask"
        let percentileValue = clamp(filters.noiseFloorPercentile, 0, 100)
        let windowBins = max(1, filters.noiseFloorWindowBins)
        let margin = filters.noiseFloorMarginDb
        let globalMin = gateValues.filter(\.isFinite).min() ?? 0
        var profile = Array(repeating: Double.nan, count: columns)
        for column in 0..<columns {
            var columnValues = [Double]()
            for row in 0..<rows {
                let value = gateValues[row * columns + column]
                if value.isFinite {
                    columnValues.append(Double(value))
                }
            }
            let aboveFloor = columnValues.filter { $0 > Double(globalMin) + 1.0e-3 }
            if aboveFloor.count >= max(3, columnValues.count / 20) {
                columnValues = aboveFloor
            }
            if !columnValues.isEmpty {
                profile[column] = percentile(columnValues, percentileValue)
            }
        }
        profile = fillNaN(rollingMedianIgnoringNaN(profile, window: windowBins))
        let ambientNoiseOutliers = filters.experimentalLongRangeNoiseEnabled
            ? ambientNoiseOutlierMask(
                companionFields: companionFields,
                valueCount: values.count,
                excessDb: filters.ambientNoiseRayExcessDb
            )
            : nil
        var masked = 0
        for row in 0..<rows {
            for column in 0..<columns {
                let index = row * columns + column
                if values[index].isFinite && shouldSuppressGate(
                    index: index,
                    row: row,
                    column: column,
                    rows: rows,
                    columns: columns,
                    gateValues: gateValues,
                    profileValue: profile[column],
                    margin: margin,
                    companionFields: companionFields,
                    ambientNoiseOutliers: ambientNoiseOutliers,
                    filters: filters
                ) {
                    values[index] = Float.nan
                    masked += 1
                }
            }
        }
        let finiteAfter = values.filter(\.isFinite).count
        return NoiseFloorResult(
            enabled: true,
            method: method,
            operation: operation,
            sourceQuantity: sourceDescription,
            marginDb: margin,
            percentile: percentileValue,
            windowBins: windowBins % 2 == 0 ? windowBins + 1 : windowBins,
            maskedCount: masked,
            finiteBefore: finiteBefore,
            finiteAfter: finiteAfter,
            floorProfile: profile.map { $0.isFinite ? $0 : nil }
        )
    }

    private func applyBackgroundModel(
        values: inout [Float],
        gateValues: [Float]?,
        companionFields: [String: [Float]],
        metadata: RadarGridMetadata,
        gateQuantity: String?,
        rows: Int,
        columns: Int,
        filters: RadarFilterSet,
        model: BackgroundModel?,
        candidate8Context: Candidate8Context?
    ) -> BackgroundModelResult {
        let finiteBefore = values.filter(\.isFinite).count
        guard filters.backgroundModelEnabled else {
            return BackgroundModelResult(enabled: false, finiteBefore: finiteBefore, finiteAfter: finiteBefore)
        }
        guard let model else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "missing_model"
            )
        }
        guard model.matches(metadata: metadata, gateQuantity: gateQuantity) else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "model_key_mismatch"
            )
        }
        guard model.statisticsVersion == BackgroundModel.candidate8StatisticsVersion else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "unsupported_background_statistics_version"
            )
        }
        let total = rows * columns
        guard model.rows == rows,
              model.columns == columns,
              values.count == total,
              model.staticEchoDateSampleCount.count == total,
              model.staticEchoDateFrequency.count == total,
              model.staticEchoSeasonCount.count == total,
              model.staticEchoTimeBucketCount.count == total,
              model.staticDBZHP10.count == total,
              model.staticDBZHMedian.count == total,
              model.staticDBZHP90.count == total else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "shape_mismatch"
            )
        }
        guard let gateValues, gateValues.count == total else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "missing_reflectivity_gate_values"
            )
        }
        guard let candidate8Context,
              candidate8Context.isComplete(valueCount: total) else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "missing_candidate8_context"
            )
        }
        if filters.backgroundRequireTrainingDiversity,
           let reason = model.trainingQualificationFailure(
               minimumDates: filters.backgroundMinTrainingDates,
               minimumSpanDays: filters.backgroundMinTrainingSpanDays
           ) {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: reason
            )
        }

        var masked = 0

        for row in 0..<rows {
            for column in 0..<columns {
                let index = row * columns + column
                guard values[index].isFinite, gateValues[index].isFinite else {
                    continue
                }
                let dbzh = Double(gateValues[index])
                let p10 = modelArrayValue(
                    model.staticDBZHP10,
                    index: index,
                    missing: .nan
                )
                let median = modelArrayValue(
                    model.staticDBZHMedian,
                    index: index,
                    missing: .nan
                )
                let p90 = modelArrayValue(
                    model.staticDBZHP90,
                    index: index,
                    missing: .nan
                )
                let seasonCoverageQualified = !model.seasonalBucketsQualified
                    || modelArrayValue(model.staticEchoSeasonCount, index: index) >= 4
                let timeCoverageQualified = !model.timeBucketsQualified
                    || modelArrayValue(model.staticEchoTimeBucketCount, index: index) >= 2
                guard modelArrayValue(model.staticEchoDateSampleCount, index: index) >= 8,
                      modelArrayValue(model.staticEchoDateFrequency, index: index) >= 0.875,
                      seasonCoverageQualified,
                      timeCoverageQualified,
                      p10.isFinite, median.isFinite, p90.isFinite,
                      dbzh <= p90 + 3,
                      dbzh <= median + 3,
                      p90 - p10 <= 6 else {
                    continue
                }
                guard let velocity = companionValue(
                    companionFields,
                    candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"],
                    index: index
                ), abs(velocity) <= 0.5,
                      let ci = companionValue(
                          companionFields,
                          candidates: ["CI", "APD", "CLUTTER_INDICATOR"],
                          index: index
                      ), ci <= 2,
                      dbzh >= 5,
                      candidate8SimilarNeighbourCount(gateValues, row: row, column: column, rows: rows, columns: columns, tolerance: 4) >= 2,
                      candidate8TemporalStaticSupport(candidate8Context, index: index, currentDBZH: dbzh) else {
                    continue
                }

                let upperSupport = candidate8UpperSupport(
                    candidate8Context,
                    index: index,
                    row: row,
                    column: column,
                    rows: rows,
                    columns: columns,
                    currentDBZH: dbzh
                )
                if upperSupport == .signal
                    || candidate8CoherentFlow(companionFields, row: row, column: column, rows: rows, columns: columns)
                    || candidate8TemporalAdvectionSupport(candidate8Context, row: row, column: column, rows: rows, columns: columns, currentDBZH: dbzh) {
                    continue
                }

                let lowSQI = companionValue(companionFields, candidates: ["SQIH", "SQI", "QIND"], index: index).map { $0 <= 0.65 } ?? false
                let rhohv = companionValue(companionFields, candidates: ["RHOHV", "RHO", "CC"], index: index)
                let lowRho = rhohv.map { $0 <= 0.85 } ?? false
                let zdr = companionValue(companionFields, candidates: ["ZDR", "ZDRH", "ZDRV"], index: index)
                let zdrOutlier = zdr.map { $0 < -3 || $0 > 8 } ?? false
                let phiTexture = localTexture(companionField(companionFields, candidates: ["PHIDP", "UPHIDP", "PHI"])?.values, row: row, column: column, rows: rows, columns: columns, angular: true) ?? 0
                let velocityTexture = localTexture(companionField(companionFields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"])?.values, row: row, column: column, rows: rows, columns: columns, angular: false) ?? 0
                let wideSpectrum = companionValue(companionFields, candidates: ["WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD"], index: index).map { $0 >= 8 } ?? false
                let qualityFamily = lowSQI
                let polarimetricFamily = lowRho || zdrOutlier || phiTexture >= 30
                let dopplerFamily = velocityTexture >= 9 || wideSpectrum
                let evidenceFamilyCount = [qualityFamily, polarimetricFamily, dopplerFamily].filter { $0 }.count
                guard lowRho || evidenceFamilyCount >= 2 else {
                    continue
                }

                values[index] = Float.nan
                masked += 1
            }
        }

        return BackgroundModelResult(
            enabled: true,
            applied: true,
            modelKey: model.modelKey,
            maskedCount: masked,
            finiteBefore: finiteBefore,
            finiteAfter: values.filter(\.isFinite).count
        )
    }

    private func modelArrayValue(
        _ values: [Float],
        index: Int,
        missing: Double = 0
    ) -> Double {
        guard values.indices.contains(index), values[index].isFinite else {
            return missing
        }
        return Double(values[index])
    }

    private func candidate8TemporalStaticSupport(_ context: Candidate8Context, index: Int, currentDBZH: Double) -> Bool {
        guard let previousDBZH = context.previousDBZH, let nextDBZH = context.nextDBZH,
              let previousVRAD = context.previousVRAD, let nextVRAD = context.nextVRAD,
              previousDBZH.indices.contains(index), nextDBZH.indices.contains(index),
              previousVRAD.indices.contains(index), nextVRAD.indices.contains(index) else {
            return false
        }
        let values = [previousDBZH[index], nextDBZH[index], previousVRAD[index], nextVRAD[index]]
        guard values.allSatisfy(\.isFinite) else { return false }
        return abs(Double(previousDBZH[index]) - currentDBZH) <= 0.5
            && abs(Double(nextDBZH[index]) - currentDBZH) <= 0.5
            && abs(Double(previousVRAD[index])) <= 0.5
            && abs(Double(nextVRAD[index])) <= 0.5
    }

    private enum Candidate8UpperSupport: Equatable {
        case absent
        case staticNuisance
        case signal
    }

    private func candidate8UpperSupport(
        _ context: Candidate8Context,
        index: Int,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        currentDBZH: Double
    ) -> Candidate8UpperSupport {
        guard let upper = context.upperElevationDBZH,
              upper.indices.contains(index),
              upper[index].isFinite,
              abs(Double(upper[index]) - currentDBZH) <= 8 else {
            return .absent
        }
        guard let upperVRAD = candidate8ContextValue(
            context.upperElevationVRAD,
            index: index
        ), abs(upperVRAD) <= 0.5 else {
            return .signal
        }
        let lowSQI = candidate8ContextValue(
            context.upperElevationSQI,
            index: index
        ).map { $0 <= 0.65 } ?? false
        let lowRHOHV = candidate8ContextValue(
            context.upperElevationRHOHV,
            index: index
        ).map { $0 <= 0.85 } ?? false
        let zdrOutlier = candidate8ContextValue(
            context.upperElevationZDR,
            index: index
        ).map { $0 < -3 || $0 > 8 } ?? false
        let phiTexture = localTexture(
            context.upperElevationPHIDP,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            angular: true
        ) ?? 0
        let velocityTexture = localTexture(
            context.upperElevationVRAD,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            angular: false
        ) ?? 0
        let wideSpectrum = candidate8ContextValue(
            context.upperElevationWidth,
            index: index
        ).map { $0 >= 8 } ?? false
        let familyCount = [
            lowSQI,
            lowRHOHV || zdrOutlier || phiTexture >= 30,
            velocityTexture >= 9 || wideSpectrum,
        ].filter { $0 }.count
        return lowRHOHV || familyCount >= 2 ? .staticNuisance : .signal
    }

    private func candidate8ContextValue(
        _ values: [Float]?,
        index: Int
    ) -> Double? {
        guard let values,
              values.indices.contains(index),
              values[index].isFinite else {
            return nil
        }
        return Double(values[index])
    }

    private func candidate8CoherentFlow(_ fields: [String: [Float]], row: Int, column: Int, rows: Int, columns: Int) -> Bool {
        guard let velocity = companionField(fields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"])?.values,
              let current = companionValue(fields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"], index: row * columns + column),
              abs(current) >= 1 else {
            return false
        }
        return candidate8SimilarNeighbourCount(velocity, row: row, column: column, rows: rows, columns: columns, tolerance: 2) >= 4
    }

    private func candidate8SimilarNeighbourCount(
        _ values: [Float]?,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        tolerance: Double
    ) -> Int {
        guard let values, rows > 0, columns > 0 else { return 0 }
        let index = row * columns + column
        guard values.indices.contains(index), values[index].isFinite else { return 0 }

        let current = Double(values[index])
        var count = 0
        for rayOffset in -1...1 {
            for gateOffset in -1...1 where rayOffset != 0 || gateOffset != 0 {
                let candidateColumn = column + gateOffset
                guard candidateColumn >= 0, candidateColumn < columns else { continue }
                let candidateRow = (row + rayOffset + rows) % rows
                let candidateIndex = candidateRow * columns + candidateColumn
                guard values.indices.contains(candidateIndex), values[candidateIndex].isFinite else { continue }
                if abs(Double(values[candidateIndex]) - current) <= tolerance {
                    count += 1
                }
            }
        }
        return count
    }

    private func candidate8TemporalAdvectionSupport(
        _ context: Candidate8Context,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        currentDBZH: Double
    ) -> Bool {
        guard let previous = context.previousDBZH,
              let next = context.nextDBZH,
              previous.count == rows * columns,
              next.count == rows * columns else {
            return false
        }
        let index = row * columns + column
        guard previous[index].isFinite, next[index].isFinite else { return false }
        let exactError = max(
            abs(currentDBZH - Double(previous[index])),
            abs(currentDBZH - Double(next[index]))
        )
        var bestShiftedError = Double.infinity
        for rayShift in -2...2 {
            for gateShift in -2...2 where rayShift != 0 || gateShift != 0 {
                let previousColumn = column - gateShift
                let nextColumn = column + gateShift
                guard previousColumn >= 0, previousColumn < columns,
                      nextColumn >= 0, nextColumn < columns else { continue }
                let previousRow = (row - rayShift + rows) % rows
                let nextRow = (row + rayShift + rows) % rows
                let previousValue = previous[previousRow * columns + previousColumn]
                let nextValue = next[nextRow * columns + nextColumn]
                guard previousValue.isFinite, nextValue.isFinite else { continue }
                bestShiftedError = min(
                    bestShiftedError,
                    max(
                        abs(currentDBZH - Double(previousValue)),
                        abs(currentDBZH - Double(nextValue))
                    )
                )
            }
        }
        return bestShiftedError.isFinite
            && bestShiftedError <= 2
            && bestShiftedError + 0.5 <= exactError
    }

    private func suppressionSourceDescription(gateQuantity: String?, companionFields: [String: [Float]]) -> String? {
        let available = [
            gateQuantity.map(normalizedQuantityKey),
            companionField(companionFields, candidates: ["CI", "APD", "CLUTTER_INDICATOR"])?.quantity,
            companionField(companionFields, candidates: ["SQIH", "SQI", "QIND"])?.quantity,
            companionField(companionFields, candidates: ["RHOHV", "RHO", "CC"])?.quantity,
            companionField(companionFields, candidates: ["ZDR", "ZDRH", "ZDRV"])?.quantity,
            companionField(companionFields, candidates: ["PHIDP", "UPHIDP", "PHI"])?.quantity,
            companionField(companionFields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"])?.quantity,
            companionField(companionFields, candidates: ["WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD"])?.quantity,
            companionField(companionFields, candidates: ["LONG_RANGE_NOISE_DBC_H", "AMBIENT_NOISE_DBC_H"])?.quantity,
            companionField(companionFields, candidates: ["LONG_RANGE_NOISE_DBC_V", "AMBIENT_NOISE_DBC_V"])?.quantity,
        ].compactMap { $0 }

        var unique = [String]()
        for quantity in available where !unique.contains(quantity) {
            unique.append(quantity)
        }
        return unique.isEmpty ? nil : unique.joined(separator: "+")
    }

    private func companionField(_ fields: [String: [Float]], candidates: [String]) -> (quantity: String, values: [Float])? {
        for candidate in candidates {
            let key = normalizedQuantityKey(candidate)
            if let values = fields[key] {
                return (key, values)
            }
        }
        return nil
    }

    private func companionValue(_ fields: [String: [Float]], candidates: [String], index: Int) -> Double? {
        guard let values = companionField(fields, candidates: candidates)?.values,
              values.indices.contains(index),
              values[index].isFinite else {
            return nil
        }
        return Double(values[index])
    }

    private func shouldSuppressGate(
        index: Int,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        gateValues: [Float],
        profileValue: Double,
        margin: Double,
        companionFields: [String: [Float]],
        ambientNoiseOutliers: [Bool]?,
        filters: RadarFilterSet
    ) -> Bool {
        let gateValue = gateValues[index]
        guard gateValue.isFinite, profileValue.isFinite else {
            return false
        }

        let dbzh = Double(gateValue)
        let floorThreshold = profileValue + margin
        if filters.receiverNoiseEnabled, shouldSuppressReceiverNoise(
            index: index,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            gateValues: gateValues,
            floorThreshold: floorThreshold,
            companionFields: companionFields,
            ambientNoiseOutliers: ambientNoiseOutliers,
            filters: filters
        ) {
            return true
        }

        if filters.staticClutterEnabled, staticClutterNeighbourCount(
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            gateValues: gateValues,
            companionFields: companionFields,
            filters: filters
        ) >= max(1, filters.staticClutterMinNeighbors) {
            return true
        }

        var score = 0

        if filters.textureCleanupEnabled, let reflectivityTexture = localTexture(
            gateValues,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            angular: false
        ) {
            let similarNeighbours = localSimilarNeighbourCount(
                gateValues,
                row: row,
                column: column,
                rows: rows,
                columns: columns,
                tolerance: filters.textureSupportDb
            )
            if reflectivityTexture >= filters.textureThresholdDb,
               similarNeighbours <= filters.textureMinSimilarNeighbors,
               dbzh <= min(floorThreshold + filters.textureNearMarginDb, filters.textureMaxDbz) {
                return true
            }
            if reflectivityTexture >= filters.textureThresholdDb + 8,
               similarNeighbours <= filters.textureMinSimilarNeighbors {
                score += 1
            }
        }

        if filters.companionQcEnabled {
            let nearNoiseFloor = dbzh <= floorThreshold + 6
            if let sqih = companionValue(companionFields, candidates: ["SQIH", "SQI", "QIND"], index: index) {
                if sqih < 0.20 {
                    score += 3
                } else if sqih < 0.45 {
                    score += 2
                } else if sqih < 0.65 {
                    score += 1
                }
            }

            if let zdr = companionValue(companionFields, candidates: ["ZDR", "ZDRH", "ZDRV"], index: index),
               zdr < -3 || zdr > 8 {
                score += 1
            }

            if let phidpTexture = localTexture(
                companionField(companionFields, candidates: ["PHIDP", "UPHIDP", "PHI"])?.values,
                row: row,
                column: column,
                rows: rows,
                columns: columns,
                angular: true
            ) {
                if phidpTexture > 60 {
                    score += 2
                } else if phidpTexture > 30 {
                    score += 1
                }
            }

            if let velocityTexture = localTexture(
                companionField(companionFields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"])?.values,
                row: row,
                column: column,
                rows: rows,
                columns: columns,
                angular: false
            ) {
                if velocityTexture > 18 {
                    score += 2
                } else if velocityTexture > 9 {
                    score += 1
                }
            }

            if let width = companionValue(companionFields, candidates: ["WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD"], index: index),
               width > 8 {
                score += 1
            }

            if nearNoiseFloor && score >= 3 {
                return true
            }
            return score >= 4
        }

        return false
    }

    private func shouldSuppressReceiverNoise(
        index: Int,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        gateValues: [Float],
        floorThreshold: Double,
        companionFields: [String: [Float]],
        ambientNoiseOutliers: [Bool]?,
        filters: RadarFilterSet
    ) -> Bool {
        guard filters.ciEvidenceEnabled,
              gateValues.indices.contains(index),
              gateValues[index].isFinite,
              Double(gateValues[index]) <= floorThreshold + filters.receiverNoiseMarginDb,
              let ci = companionValue(companionFields, candidates: ["CI", "APD", "CLUTTER_INDICATOR"], index: index),
              ci >= filters.ciNoiseMinDb,
              let sqi = companionValue(companionFields, candidates: ["SQIH", "SQI", "QIND"], index: index),
              sqi <= filters.receiverNoiseSqiMax else {
            return false
        }

        var badMoments = 0
        if let phiDPTexture = localTexture(
            companionField(companionFields, candidates: ["PHIDP", "UPHIDP", "PHI"])?.values,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            angular: true
        ), phiDPTexture >= filters.receiverNoisePhiDPTextureMin {
            badMoments += 1
        }
        if let velocityTexture = localTexture(
            companionField(companionFields, candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"])?.values,
            row: row,
            column: column,
            rows: rows,
            columns: columns,
            angular: false
        ), velocityTexture >= filters.receiverNoiseVelocityTextureMin {
            badMoments += 1
        }
        if let rhohv = companionValue(companionFields, candidates: ["RHOHV", "RHO", "CC"], index: index),
           rhohv <= filters.receiverNoiseRhohvMax {
            badMoments += 1
        }
        if let zdr = companionValue(companionFields, candidates: ["ZDR", "ZDRH", "ZDRV"], index: index),
           zdr <= -3 || zdr >= 8 {
            badMoments += 1
        }
        if let ambientNoiseOutliers,
           ambientNoiseOutliers.indices.contains(index),
           ambientNoiseOutliers[index] {
            badMoments += 1
        }
        return badMoments >= max(1, filters.receiverNoiseMinBadMoments)
    }

    private func ambientNoiseOutlierMask(
        companionFields: [String: [Float]],
        valueCount: Int,
        excessDb: Double
    ) -> [Bool]? {
        var combined = Array(repeating: false, count: valueCount)
        var hasAvailableField = false
        for candidates in [
            ["LONG_RANGE_NOISE_DBC_H", "AMBIENT_NOISE_DBC_H"],
            ["LONG_RANGE_NOISE_DBC_V", "AMBIENT_NOISE_DBC_V"],
        ] {
            guard let values = companionField(companionFields, candidates: candidates)?.values,
                  values.count == valueCount else {
                continue
            }
            let finite = values.filter(\.isFinite).map(Double.init)
            guard !finite.isEmpty else { continue }
            let median = percentile(finite, 50)
            guard median > -20 else { continue }
            hasAvailableField = true
            for index in values.indices where values[index].isFinite && Double(values[index]) >= median + excessDb {
                combined[index] = true
            }
        }
        return hasAvailableField ? combined : nil
    }

    private func staticClutterNeighbourCount(
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        gateValues: [Float],
        companionFields: [String: [Float]],
        filters: RadarFilterSet
    ) -> Int {
        guard rows > 0, columns > 0 else {
            return 0
        }
        var count = 0
        for rowOffset in -1...1 {
            let neighbourRow = (row + rowOffset + rows) % rows
            for columnOffset in -1...1 {
                let neighbourColumn = column + columnOffset
                guard neighbourColumn >= 0, neighbourColumn < columns else {
                    continue
                }
                let neighbourIndex = neighbourRow * columns + neighbourColumn
                if isStaticClutterCandidate(
                    index: neighbourIndex,
                    gateValues: gateValues,
                    companionFields: companionFields,
                    filters: filters
                ) {
                    count += 1
                }
            }
        }
        return count
    }

    private func isStaticClutterCandidate(
        index: Int,
        gateValues: [Float],
        companionFields: [String: [Float]],
        filters: RadarFilterSet
    ) -> Bool {
        guard gateValues.indices.contains(index), gateValues[index].isFinite else {
            return false
        }
        let dbzh = Double(gateValues[index])
        guard dbzh >= filters.staticClutterDbzMin,
              (!filters.ciEvidenceEnabled || (
                  companionValue(
                      companionFields,
                      candidates: ["CI", "APD", "CLUTTER_INDICATOR"],
                      index: index
                  ).map { $0 <= filters.ciClutterMaxDb } ?? false
              )),
              let velocity = companionValue(
                  companionFields,
                  candidates: ["VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"],
                  index: index
              ) else {
            return false
        }
        return abs(velocity) <= filters.staticClutterVradAbsMax
    }

    private func localTexture(_ values: [Float]?, row: Int, column: Int, rows: Int, columns: Int, angular: Bool) -> Double? {
        guard let values, rows > 0, columns > 0 else {
            return nil
        }
        let index = row * columns + column
        guard values.indices.contains(index), values[index].isFinite else {
            return nil
        }

        let current = Double(values[index])
        let neighbours = [
            ((row + rows - 1) % rows, column),
            ((row + 1) % rows, column),
            (row, max(0, column - 1)),
            (row, min(columns - 1, column + 1)),
        ]
        let differences = neighbours.compactMap { neighbour -> Double? in
            let neighbourIndex = neighbour.0 * columns + neighbour.1
            guard neighbourIndex != index,
                  values.indices.contains(neighbourIndex),
                  values[neighbourIndex].isFinite else {
                return nil
            }
            let neighbourValue = Double(values[neighbourIndex])
            return angular ? angularDifferenceDegrees(current, neighbourValue) : abs(current - neighbourValue)
        }
        guard differences.count >= 2 else {
            return nil
        }
        return percentile(differences, 75)
    }

    private func localSimilarNeighbourCount(
        _ values: [Float]?,
        row: Int,
        column: Int,
        rows: Int,
        columns: Int,
        tolerance: Double
    ) -> Int {
        guard let values, rows > 0, columns > 0 else {
            return 0
        }
        let index = row * columns + column
        guard values.indices.contains(index), values[index].isFinite else {
            return 0
        }

        let current = Double(values[index])
        let neighbours = [
            ((row + rows - 1) % rows, column),
            ((row + 1) % rows, column),
            (row, max(0, column - 1)),
            (row, min(columns - 1, column + 1)),
        ]
        return neighbours.reduce(0) { count, neighbour in
            let neighbourIndex = neighbour.0 * columns + neighbour.1
            guard neighbourIndex != index,
                  values.indices.contains(neighbourIndex),
                  values[neighbourIndex].isFinite else {
                return count
            }
            return abs(Double(values[neighbourIndex]) - current) <= tolerance ? count + 1 : count
        }
    }

    private func angularDifferenceDegrees(_ first: Double, _ second: Double) -> Double {
        var difference = abs(first - second).truncatingRemainder(dividingBy: 360)
        if difference > 180 {
            difference = 360 - difference
        }
        return difference
    }

    private func scale(values: [Float], scaleMin: Double?, scaleMax: Double?, maskBelowMin: Bool) -> (scaled: [UInt8], valid: [Bool], stats: PPIStats) {
        let finite = values.compactMap(finiteDouble)
        guard !finite.isEmpty else {
            return (
                Array(repeating: 0, count: values.count),
                Array(repeating: false, count: values.count),
                PPIStats(validMin: nil, validMax: nil, scaleMin: nil, scaleMax: nil)
            )
        }

        let lower = scaleMin ?? percentile(finite, 2)
        var upper = scaleMax ?? percentile(finite, 98)
        if upper <= lower {
            upper = lower + 1
        }

        var scaled = Array(repeating: UInt8(0), count: values.count)
        var valid = Array(repeating: false, count: values.count)
        for (index, value) in values.enumerated() {
            guard value.isFinite else { continue }
            if maskBelowMin && Double(value) < lower { continue }
            let normalized = clamp((Double(value) - lower) / (upper - lower), 0, 1)
            scaled[index] = UInt8(clamp(round(normalized * 255), 0, 255))
            valid[index] = true
        }
        return (
            scaled,
            valid,
            PPIStats(validMin: finite.min(), validMax: finite.max(), scaleMin: lower, scaleMax: upper)
        )
    }

    private func geographicPoint(metadata: RadarGridMetadata, xM: Double, yM: Double) -> (longitude: Double, latitude: Double) {
        let earthRadiusM = 6_371_000.0
        let lat0 = metadata.latitude * Double.pi / 180
        let lon0 = metadata.longitude * Double.pi / 180
        let rho = hypot(xM, yM)
        guard rho > 0 else { return (metadata.longitude, metadata.latitude) }
        let c = rho / earthRadiusM
        let lat = asin(cos(c) * sin(lat0) + (yM * sin(c) * cos(lat0) / rho))
        let lon = lon0 + atan2(
            xM * sin(c),
            rho * cos(lat0) * cos(c) - yM * sin(lat0) * sin(c)
        )
        return (lon * 180 / Double.pi, lat * 180 / Double.pi)
    }
}

func finiteDouble(_ value: Float) -> Double? {
    value.isFinite ? Double(value) : nil
}

func percentile(_ values: [Double], _ percentileValue: Double) -> Double {
    let sorted = values.filter(\.isFinite).sorted()
    guard !sorted.isEmpty else { return Double.nan }
    if sorted.count == 1 { return sorted[0] }
    let position = clamp(percentileValue, 0, 100) / 100 * Double(sorted.count - 1)
    let lower = Int(floor(position))
    let upper = Int(ceil(position))
    if lower == upper { return sorted[lower] }
    let fraction = position - Double(lower)
    return sorted[lower] + (sorted[upper] - sorted[lower]) * fraction
}

func rollingMedian(_ values: [Double], window: Int) -> [Double] {
    let adjustedWindow = max(1, window % 2 == 0 ? window + 1 : window)
    guard adjustedWindow > 1 else { return values }
    let half = adjustedWindow / 2
    return values.indices.map { index in
        let lower = max(0, index - half)
        let upper = min(values.count - 1, index + half)
        return percentile(Array(values[lower...upper]), 50)
    }
}

func rollingMedianIgnoringNaN(_ values: [Double], window: Int) -> [Double] {
    let adjustedWindow = max(1, window % 2 == 0 ? window + 1 : window)
    guard adjustedWindow > 1 else { return values }
    let half = adjustedWindow / 2
    return values.indices.map { index in
        let lower = max(0, index - half)
        let upper = min(values.count - 1, index + half)
        let segment = values[lower...upper].filter(\.isFinite)
        return segment.isEmpty ? Double.nan : percentile(Array(segment), 50)
    }
}

func fillNaN(_ values: [Double]) -> [Double] {
    guard values.contains(where: { !$0.isFinite }) else { return values }
    let valid = values.enumerated().filter { $0.element.isFinite }
    guard !valid.isEmpty else { return Array(repeating: 0, count: values.count) }
    var output = values
    for index in values.indices where !values[index].isFinite {
        let left = valid.last { $0.offset < index }
        let right = valid.first { $0.offset > index }
        if let left, let right {
            let span = Double(right.offset - left.offset)
            let fraction = Double(index - left.offset) / span
            output[index] = left.element + (right.element - left.element) * fraction
        } else if let left {
            output[index] = left.element
        } else if let right {
            output[index] = right.element
        }
    }
    return output
}

func clamp(_ value: Double, _ lower: Double, _ upper: Double) -> Double {
    min(max(value, lower), upper)
}
