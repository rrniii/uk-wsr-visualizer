import CoreLocation
import Foundation
import MapKit
import OSLog
import UIKit

private struct DecodedFieldCacheKey: Hashable {
    var filePath: String
    var selection: FieldSelection
}

private struct RenderedFrameCacheKey: Hashable {
    var field: DecodedFieldCacheKey
    var filters: RadarFilterSet
    var candidate8ContextKey: String?
}

struct Candidate8FieldSource: Hashable {
    var fileURL: URL
    var selection: FieldSelection
}

struct Candidate8ContextSources: Hashable {
    var previous: Candidate8FieldSource
    var next: Candidate8FieldSource
    var upper: Candidate8FieldSource?
    var upperElevationRequired: Bool

    var cacheKey: String {
        [
            previous.fileURL.standardizedFileURL.path,
            previous.selection.time,
            next.fileURL.standardizedFileURL.path,
            next.selection.time,
            upper?.fileURL.standardizedFileURL.path ?? "",
            upper?.selection.dataset ?? "",
            upperElevationRequired ? "upper-required" : "upper-optional",
        ].joined(separator: "|")
    }
}

struct RegisteredBackgroundModelCandidate {
    var url: URL
    var eligibleForValidatedRuntime: Bool
}

actor RadarRenderWorker {
    private let reader: RadarVolumeReader
    private let renderer = RadarRenderer()
    private var loadedBackgroundModels: [String: BackgroundModel] = [:]
    private var decodedFields: [DecodedFieldCacheKey: (field: PolarField, cost: Int, access: UInt64)] = [:]
    private var renderedFrames: [RenderedFrameCacheKey: (frame: PPIFrame, cost: Int, access: UInt64)] = [:]
    private var cacheAccess: UInt64 = 0
    private let memoryLimitBytes = 192 * 1024 * 1024

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
        try renderFrameWithTimings(
            from: fileURL,
            item: item,
            selection: selection,
            filters: filters,
            backgroundModels: backgroundModels
        ).frame
    }

    func renderFrameWithTimings(
        from fileURL: URL,
        item: CatalogItem,
        selection: FieldSelection,
        filters: RadarFilterSet,
        backgroundModels: [BackgroundModelDescriptor],
        candidate8ContextSources: Candidate8ContextSources? = nil
    ) throws -> VideoFrameRenderResult {
        let overallState = RadarPerformanceTrace.signposter.beginInterval("Decode and QC")
        defer {
            RadarPerformanceTrace.signposter.endInterval("Decode and QC", overallState)
        }
        try Task.checkCancellation()
        let fieldKey = DecodedFieldCacheKey(filePath: fileURL.standardizedFileURL.path, selection: selection)
        let frameKey = RenderedFrameCacheKey(
            field: fieldKey,
            filters: filters,
            candidate8ContextKey: candidate8ContextSources?.cacheKey
        )
        if let cached = renderedFrames[frameKey] {
            touchRenderedFrame(frameKey, cached: cached)
            return VideoFrameRenderResult(
                frame: cached.frame,
                hdf5ReadSeconds: 0,
                radarRenderSeconds: 0,
                decodedCacheHit: true,
                renderedCacheHit: true
            )
        }

        let readStart = Date()
        let decodedCacheHit: Bool
        let field: PolarField
        if let cached = decodedFields[fieldKey] {
            touchDecodedField(fieldKey, cached: cached)
            field = cached.field
            decodedCacheHit = true
        } else {
            let readState = RadarPerformanceTrace.signposter.beginInterval("HDF5 read")
            field = try reader.readPolarField(from: fileURL, item: item, selection: selection)
            RadarPerformanceTrace.signposter.endInterval("HDF5 read", readState)
            decodedCacheHit = false
            storeDecodedField(field, for: fieldKey)
        }
        let readSeconds = Date().timeIntervalSince(readStart)
        try Task.checkCancellation()
        let renderStart = Date()
        let renderState = RadarPerformanceTrace.signposter.beginInterval("Radar QC render")
        let backgroundModel = matchingBackgroundModel(
            for: field,
            in: backgroundModels,
            runtimeMode: filters.qcRuntimeMode
        )
        let candidate8Context: Candidate8Context?
        if let candidate8ContextSources {
            candidate8Context = buildCandidate8Context(
                from: candidate8ContextSources,
                current: field,
                item: item
            )
        } else {
            candidate8Context = nil
        }
        let frame = renderer.render(
            field: field,
            filters: filters,
            backgroundModel: backgroundModel,
            candidate8Context: candidate8Context
        )
        RadarPerformanceTrace.signposter.endInterval("Radar QC render", renderState)
        let renderSeconds = Date().timeIntervalSince(renderStart)
        try Task.checkCancellation()
        storeRenderedFrame(frame, for: frameKey)
        return VideoFrameRenderResult(
            frame: frame,
            hdf5ReadSeconds: decodedCacheHit ? 0 : readSeconds,
            radarRenderSeconds: renderSeconds,
            decodedCacheHit: decodedCacheHit,
            renderedCacheHit: false
        )
    }

    func prepareField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws {
        try Task.checkCancellation()
        let key = DecodedFieldCacheKey(filePath: fileURL.standardizedFileURL.path, selection: selection)
        if let cached = decodedFields[key] {
            touchDecodedField(key, cached: cached)
            return
        }
        let field = try reader.readPolarField(from: fileURL, item: item, selection: selection)
        try Task.checkCancellation()
        storeDecodedField(field, for: key)
    }

    func clearMemoryCache() {
        decodedFields.removeAll(keepingCapacity: false)
        renderedFrames.removeAll(keepingCapacity: false)
    }

    private func matchingBackgroundModel(
        for field: PolarField,
        in models: [BackgroundModelDescriptor],
        runtimeMode: QCV3RuntimeMode
    ) -> BackgroundModel? {
        let gateQuantity = field.gateQuantity ?? (isReflectivityQuantity(field.metadata.quantity) ? field.metadata.quantity : nil)
        guard runtimeMode != .safe,
              let descriptor = models.first(where: {
                  $0.matches(
                      metadata: field.metadata,
                      gateQuantity: gateQuantity
                  ) && (
                      runtimeMode == .shadow
                          || $0.eligibleForValidatedRuntime
                  )
              }) else {
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

    private func buildCandidate8Context(
        from sources: Candidate8ContextSources,
        current: PolarField,
        item: CatalogItem
    ) -> Candidate8Context? {
        guard let previous = try? decodedField(from: sources.previous.fileURL, item: item, selection: sources.previous.selection),
              let next = try? decodedField(from: sources.next.fileURL, item: item, selection: sources.next.selection),
              fieldsAreAligned(current, previous),
              fieldsAreAligned(current, next),
              let previousDBZH = reflectivityValues(from: previous),
              let nextDBZH = reflectivityValues(from: next),
              let previousVRAD = velocityValues(from: previous),
              let nextVRAD = velocityValues(from: next) else {
            return nil
        }

        let upperDBZH: [Float]?
        let upperVRAD: [Float]?
        let upperSQI: [Float]?
        let upperRHOHV: [Float]?
        let upperZDR: [Float]?
        let upperPHIDP: [Float]?
        let upperWidth: [Float]?
        if let upper = sources.upper {
            guard let upperField = try? decodedField(from: upper.fileURL, item: item, selection: upper.selection),
                  fieldsAreAligned(current, upperField),
                  let values = reflectivityValues(from: upperField) else {
                return nil
            }
            upperDBZH = values
            upperVRAD = velocityValues(from: upperField)
            upperSQI = companionValues(
                from: upperField,
                candidates: ["SQIH", "SQI", "QIND"]
            )
            upperRHOHV = companionValues(
                from: upperField,
                candidates: ["RHOHV", "RHO", "CC"]
            )
            upperZDR = companionValues(
                from: upperField,
                candidates: ["ZDR", "ZDRH", "ZDRV"]
            )
            upperPHIDP = companionValues(
                from: upperField,
                candidates: ["PHIDP", "UPHIDP", "PHI"]
            )
            upperWidth = companionValues(
                from: upperField,
                candidates: [
                    "WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD",
                ]
            )
        } else {
            upperDBZH = nil
            upperVRAD = nil
            upperSQI = nil
            upperRHOHV = nil
            upperZDR = nil
            upperPHIDP = nil
            upperWidth = nil
        }
        let context = Candidate8Context(
            previousDBZH: previousDBZH,
            nextDBZH: nextDBZH,
            previousVRAD: previousVRAD,
            nextVRAD: nextVRAD,
            upperElevationDBZH: upperDBZH,
            upperElevationVRAD: upperVRAD,
            upperElevationSQI: upperSQI,
            upperElevationRHOHV: upperRHOHV,
            upperElevationZDR: upperZDR,
            upperElevationPHIDP: upperPHIDP,
            upperElevationWidth: upperWidth,
            upperElevationRequired: sources.upperElevationRequired
        )
        return context.isComplete(valueCount: current.values.count) ? context : nil
    }

    private func decodedField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        let key = DecodedFieldCacheKey(filePath: fileURL.standardizedFileURL.path, selection: selection)
        if let cached = decodedFields[key] {
            touchDecodedField(key, cached: cached)
            return cached.field
        }
        let field = try reader.readPolarField(from: fileURL, item: item, selection: selection)
        storeDecodedField(field, for: key)
        return field
    }

    private func fieldsAreAligned(_ current: PolarField, _ candidate: PolarField) -> Bool {
        current.rows == candidate.rows
            && current.columns == candidate.columns
            && current.metadata.radar.caseInsensitiveCompare(candidate.metadata.radar) == .orderedSame
            && current.metadata.pulse.caseInsensitiveCompare(candidate.metadata.pulse) == .orderedSame
            && abs(current.metadata.rstartKm - candidate.metadata.rstartKm) <= 0.001
            && abs(current.metadata.rscaleM - candidate.metadata.rscaleM) <= 0.001
    }

    private func reflectivityValues(from field: PolarField) -> [Float]? {
        if let values = field.gateValues, values.count == field.values.count {
            return values
        }
        return isReflectivityQuantity(field.metadata.quantity) ? field.values : nil
    }

    private func velocityValues(from field: PolarField) -> [Float]? {
        companionValues(
            from: field,
            candidates: [
                "VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV",
            ]
        )
    }

    private func companionValues(
        from field: PolarField,
        candidates: [String]
    ) -> [Float]? {
        for candidate in candidates {
            let key = normalizedQuantityKey(candidate)
            if let values = field.companionFields[key], values.count == field.values.count {
                return values
            }
        }
        return nil
    }

    private func touchDecodedField(
        _ key: DecodedFieldCacheKey,
        cached: (field: PolarField, cost: Int, access: UInt64)
    ) {
        cacheAccess &+= 1
        decodedFields[key] = (cached.field, cached.cost, cacheAccess)
    }

    private func touchRenderedFrame(
        _ key: RenderedFrameCacheKey,
        cached: (frame: PPIFrame, cost: Int, access: UInt64)
    ) {
        cacheAccess &+= 1
        renderedFrames[key] = (cached.frame, cached.cost, cacheAccess)
    }

    private func storeDecodedField(_ field: PolarField, for key: DecodedFieldCacheKey) {
        cacheAccess &+= 1
        let arrayCount = field.values.count +
            (field.gateValues?.count ?? 0) +
            field.companionFields.values.reduce(0) { $0 + $1.count }
        decodedFields[key] = (field, max(1, arrayCount * MemoryLayout<Float>.stride), cacheAccess)
        trimMemoryCache()
    }

    private func storeRenderedFrame(_ frame: PPIFrame, for key: RenderedFrameCacheKey) {
        cacheAccess &+= 1
        let cost = frame.scaled.count +
            frame.valid.count +
            (frame.filteredValues.count + frame.originalValues.count) * MemoryLayout<Float>.stride
        renderedFrames[key] = (frame, max(1, cost), cacheAccess)
        trimMemoryCache()
    }

    private func trimMemoryCache() {
        var total = decodedFields.values.reduce(0) { $0 + $1.cost } +
            renderedFrames.values.reduce(0) { $0 + $1.cost }
        while total > memoryLimitBytes {
            let oldestDecoded = decodedFields.min { $0.value.access < $1.value.access }
            let oldestRendered = renderedFrames.min { $0.value.access < $1.value.access }
            if let decoded = oldestDecoded,
               oldestRendered == nil || decoded.value.access <= oldestRendered!.value.access {
                total -= decoded.value.cost
                decodedFields.removeValue(forKey: decoded.key)
            } else if let rendered = oldestRendered {
                total -= rendered.value.cost
                renderedFrames.removeValue(forKey: rendered.key)
            } else {
                break
            }
        }
    }
}
