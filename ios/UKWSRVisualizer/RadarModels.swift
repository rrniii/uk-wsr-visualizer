import Foundation
import SwiftUI

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

    var geometryClass: String? {
        key["geometry_class"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
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
