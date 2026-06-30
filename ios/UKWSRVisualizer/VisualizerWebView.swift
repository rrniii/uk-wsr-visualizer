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

struct RadarFilterSet: Hashable {
    var minRangeKm: Double?
    var maxRangeKm: Double?
    var minAzimuthDeg: Double?
    var maxAzimuthDeg: Double?
    var minValue: Double?
    var maxValue: Double?
    var cappiHeightM: Double?
    var displayMin: Double?
    var displayMax: Double?
    var palette: String = "auto"
    var opacity: Double = 0.88
    var noiseFloorEnabled: Bool = false
    var noiseFloorMarginDb: Double = 3
}

struct NoiseFloorResult: Hashable {
    var enabled: Bool
    var method: String = "estimated"
    var operation: String = "mask"
    var marginDb: Double?
    var percentile: Double?
    var windowBins: Int?
    var maskedCount: Int = 0
    var finiteBefore: Int = 0
    var finiteAfter: Int = 0
    var floorProfile: [Double?] = []
}

struct PPIStats: Hashable {
    var validMin: Double?
    var validMax: Double?
    var scaleMin: Double?
    var scaleMax: Double?
}

struct PolarField {
    var values: [Float]
    var rows: Int
    var columns: Int
    var metadata: RadarGridMetadata
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

    func index(row: Int, column: Int) -> Int {
        max(0, min(rows - 1, row)) * columns + max(0, min(columns - 1, column))
    }
}

struct IdentifyResult: Hashable {
    var row: Int
    var column: Int
    var value: Double?
    var originalValue: Double?
    var maskedByNoiseFloor: Bool
    var rangeM: Double
    var rangeKm: Double
    var azimuthDeg: Double
    var longitude: Double
    var latitude: Double
    var elevationDeg: Double?

    var compactDescription: String {
        let valueText = value.map { String(format: "%.2f", $0) } ?? (maskedByNoiseFloor ? "masked" : "no data")
        return "\(valueText)  \(String(format: "%.1f", rangeKm)) km  \(String(format: "%.1f", azimuthDeg)) deg"
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

        if ["DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"].contains(upper) || lower.contains("reflectivity") {
            palette = palette.isEmpty ? "homeyer" : palette
            limits = (-30, 75)
            maskBelowMin = true
        } else if ["VRAD", "VRADH", "VRADV", "VEL", "VELH", "VELV", "V"].contains(upper) || lower.contains("velocity") {
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
        } else if ["SNR", "SNRH", "SNRV", "NCP", "NCPH", "NCPV"].contains(upper) || lower.contains("signal_to_noise") {
            palette = palette.isEmpty ? "Carbone17" : palette
            limits = upper.hasPrefix("SNR") || lower.contains("signal_to_noise") ? (-20, 30) : (0, 1)
        } else {
            palette = palette.isEmpty ? "gray" : palette
        }

        return DisplayConfig(palette: palette, scaleMin: limits.0, scaleMax: limits.1, maskBelowMin: maskBelowMin)
    }
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

        var cField = UKHDF5PolarField()
        var errorBuffer = [CChar](repeating: 0, count: 512)
        let requestedDataset = selection.dataset ?? ""

        let didRead = fileURL.withUnsafeFileSystemRepresentation { pathPointer -> Int32 in
            guard let pathPointer else { return 0 }
            return requestedDataset.withCString { datasetPointer in
                selection.quantity.withCString { quantityPointer in
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
        let decodedDataset = fixedCString(cField.datasetName)
        let decodedQuantity = fixedCString(cField.quantity)
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: decodedQuantity.isEmpty ? selection.quantity : decodedQuantity,
            dataset: decodedDataset.isEmpty ? selection.dataset ?? "auto" : decodedDataset,
            latitude: cField.latitude.isFinite ? cField.latitude : 0,
            longitude: cField.longitude.isFinite ? cField.longitude : 0,
            heightM: cField.heightM.isFinite ? cField.heightM : nil,
            elevationDeg: cField.elevationDeg.isFinite ? cField.elevationDeg : nil,
            rstartKm: cField.rstartKm.isFinite ? cField.rstartKm : 0,
            rscaleM: cField.rscaleM.isFinite ? cField.rscaleM : 1000,
            nbins: columns,
            nrays: rows
        )

        return PolarField(values: values, rows: rows, columns: columns, metadata: metadata)
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
        return PolarField(values: values, rows: rows, columns: columns, metadata: metadata)
    }
}

struct RadarRenderer {
    func render(field: PolarField, filters: RadarFilterSet, maxRays: Int = 360, maxBins: Int = 320) -> PPIFrame {
        var filtered = applyBasicFilters(values: field.values, rows: field.rows, columns: field.columns, metadata: field.metadata, filters: filters)
        let noise = applyNoiseFloor(values: &filtered, rows: field.rows, columns: field.columns, filters: filters)
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
        let scaleMin = filters.displayMin ?? display.scaleMin
        let scaleMax = filters.displayMax ?? display.scaleMax
        let scaling = scale(values: sampled, scaleMin: scaleMin, scaleMax: scaleMax, maskBelowMin: display.maskBelowMin)

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
            noiseFloor: noise
        )
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
            value: value,
            originalValue: original,
            maskedByNoiseFloor: original != nil && value == nil,
            rangeM: rangeM,
            rangeKm: rangeM / 1000,
            azimuthDeg: azimuthDeg,
            longitude: point.longitude,
            latitude: point.latitude,
            elevationDeg: frame.metadata.elevationDeg
        )
    }

    private func applyBasicFilters(values: [Float], rows: Int, columns: Int, metadata: RadarGridMetadata, filters: RadarFilterSet) -> [Float] {
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

    private func applyNoiseFloor(values: inout [Float], rows: Int, columns: Int, filters: RadarFilterSet) -> NoiseFloorResult {
        let finiteBefore = values.filter(\.isFinite).count
        guard filters.noiseFloorEnabled else {
            return NoiseFloorResult(enabled: false, finiteBefore: finiteBefore, finiteAfter: finiteBefore)
        }

        let globalMin = values.filter(\.isFinite).min() ?? 0
        var profile = Array(repeating: Double.nan, count: columns)
        for column in 0..<columns {
            var columnValues = [Double]()
            for row in 0..<rows {
                let value = values[row * columns + column]
                if value.isFinite {
                    columnValues.append(Double(value))
                }
            }
            let aboveFloor = columnValues.filter { $0 > Double(globalMin) + 1.0e-3 }
            if aboveFloor.count >= max(3, columnValues.count / 20) {
                columnValues = aboveFloor
            }
            if !columnValues.isEmpty {
                profile[column] = percentile(columnValues, 10)
            }
        }
        profile = fillNaN(profile)
        profile = rollingMedian(profile, window: 11)
        let margin = filters.noiseFloorMarginDb
        var masked = 0
        for row in 0..<rows {
            for column in 0..<columns {
                let index = row * columns + column
                if values[index].isFinite && Double(values[index]) <= profile[column] + margin {
                    values[index] = Float.nan
                    masked += 1
                }
            }
        }
        let finiteAfter = values.filter(\.isFinite).count
        return NoiseFloorResult(
            enabled: true,
            marginDb: margin,
            percentile: 10,
            windowBins: 11,
            maskedCount: masked,
            finiteBefore: finiteBefore,
            finiteAfter: finiteAfter,
            floorProfile: profile.map { $0.isFinite ? $0 : nil }
        )
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
