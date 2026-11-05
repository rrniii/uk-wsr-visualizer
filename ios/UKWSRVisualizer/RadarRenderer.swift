import Foundation
import SwiftUI

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
        guard model.geometryClass == "ppi" else {
            return BackgroundModelResult(
                enabled: true,
                applied: false,
                modelKey: model.modelKey,
                finiteBefore: finiteBefore,
                finiteAfter: finiteBefore,
                reason: "unsupported_background_geometry"
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
                let dbzhFloat = gateValues[index]
                let dbzh = Double(dbzhFloat)
                let p10 = model.staticDBZHP10[index]
                let median = model.staticDBZHMedian[index]
                let p90 = model.staticDBZHP90[index]
                guard modelArrayValue(model.staticEchoDateSampleCount, index: index) >= 8,
                      modelArrayValue(model.staticEchoDateFrequency, index: index) >= 0.875,
                      modelArrayValue(model.staticEchoSeasonCount, index: index) >= 4,
                      modelArrayValue(model.staticEchoTimeBucketCount, index: index) >= 2,
                      p10.isFinite, median.isFinite, p90.isFinite,
                      dbzhFloat <= p90 + Float(3),
                      dbzhFloat <= median + Float(3),
                      p90 - p10 <= Float(6) else {
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

        let current = values[index]
        let toleranceFloat = Float(tolerance)
        var count = 0
        for rayOffset in -1...1 {
            for gateOffset in -1...1 where rayOffset != 0 || gateOffset != 0 {
                let candidateColumn = column + gateOffset
                guard candidateColumn >= 0, candidateColumn < columns else { continue }
                let candidateRow = (row + rayOffset + rows) % rows
                let candidateIndex = candidateRow * columns + candidateColumn
                guard values.indices.contains(candidateIndex), values[candidateIndex].isFinite else { continue }
                if abs(values[candidateIndex] - current) <= toleranceFloat {
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
