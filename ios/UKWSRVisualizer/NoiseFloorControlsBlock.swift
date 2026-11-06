import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct NoiseFloorControlsBlock: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var isShowingAdvanced = false
    @State private var isShowingDetails = false

    private struct CleanupDetailRow: Identifiable {
        var label: String
        var value: String
        var id: String { label }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Remove noise/clutter")
                    .font(.subheadline.weight(.semibold))
            }

            Picker("Cleaning mode", selection: cleanupPresetBinding) {
                ForEach(NoiseCleanupPreset.allCases) { preset in
                    Text(preset.title).tag(preset)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("CleanupModePicker")

            HStack(alignment: .firstTextBaseline) {
                Text(activeCleanupPreset.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Spacer(minLength: 8)
            }

            DisclosureGroup(isExpanded: $isShowingDetails) {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(cleaningDetailRows) { row in
                        LabeledContent(row.label, value: row.value)
                            .font(.caption2.monospacedDigit())
                    }

                    Button {
                        isShowingAdvanced = true
                    } label: {
                        Label("Advanced settings", systemImage: "slider.horizontal.3")
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .padding(.top, 2)
                }
                .foregroundStyle(.secondary)
                .padding(.top, 4)
            } label: {
                Text(cleaningSummaryText)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
        .sheet(isPresented: $isShowingAdvanced) {
            NoiseCleanupAdvancedSheet(model: model)
                .presentationDetents([.medium])
        }
    }

    private var activeCleanupPreset: NoiseCleanupPreset {
        model.filters.noiseFloorEnabled ? NoiseCleanupPreset.nearest(to: model.filters.receiverNoiseMarginDb) : .off
    }

    private var cleanupPresetBinding: Binding<NoiseCleanupPreset> {
        Binding(
            get: { activeCleanupPreset },
            set: { preset in
                preset.apply(to: &model.filters)
                model.filtersChanged()
            }
        )
    }

    private var cleaningSummaryText: String {
        guard model.filters.noiseFloorEnabled else {
            return "Cleanup off"
        }
        guard let frame = model.frame else {
            return "Render a scan to see cleanup evidence"
        }
        guard frame.noiseFloor.enabled else {
            if frame.backgroundModel.enabled, let reason = frame.backgroundModel.reason {
                return "Learned background not applied: \(reason)"
            }
            return "No compatible reflectivity/quality evidence for this field"
        }
        let before = max(frame.noiseFloor.finiteBefore, 1)
        let percent = Double(frame.qcV3.removedCount) / Double(before) * 100
        if frame.qcV3.proposedRemovedCount > frame.qcV3.removedCount {
            return String(
                format: "QC v3: %.1f%% removed, %d shadow proposals",
                percent,
                frame.qcV3.proposedRemovedCount - frame.qcV3.removedCount
            )
        }
        return String(format: "QC v3: %.1f%% removed", percent)
    }

    private var cleaningDetailRows: [CleanupDetailRow] {
        guard model.filters.noiseFloorEnabled else {
            return [CleanupDetailRow(label: "Mode", value: "Off")]
        }
        guard let frame = model.frame else {
            return [CleanupDetailRow(label: "Evidence", value: "Render a scan first")]
        }
        guard frame.noiseFloor.enabled else {
            if frame.backgroundModel.enabled, let reason = frame.backgroundModel.reason {
                return [CleanupDetailRow(label: "Learned background", value: reason)]
            }
            return [CleanupDetailRow(label: "Evidence", value: "No compatible reflectivity or quality fields")]
        }

        var rows: [CleanupDetailRow] = []
        rows.append(CleanupDetailRow(label: "Mode", value: frame.qcV3.mode.rawValue.capitalized))
        let source = frame.noiseFloor.sourceQuantity?
            .split(separator: "+")
            .map(String.init)
            .joined(separator: ", ") ?? "DBZH"
        rows.append(CleanupDetailRow(label: "Evidence fields", value: source))
        rows.append(CleanupDetailRow(label: "Noise", value: "\(frame.noiseFloor.maskedCount) of \(frame.noiseFloor.finiteBefore) gates"))
        if frame.backgroundModel.applied {
            rows.append(CleanupDetailRow(label: "Learned background", value: "\(frame.backgroundModel.maskedCount) gates"))
        } else if frame.backgroundModel.enabled, let reason = frame.backgroundModel.reason {
            rows.append(CleanupDetailRow(label: "Learned background", value: reason))
        }
        rows.append(CleanupDetailRow(label: "Bundle", value: frame.qcV3.bundleQualification))
        return rows
    }

}

private enum NoiseCleanupPreset: String, CaseIterable, Identifiable {
    case off
    case normal

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off:
            return "Off"
        case .normal:
            return "Normal"
        }
    }

    var marginDb: Double {
        switch self {
        case .off:
            return 0
        case .normal:
            return 0.25
        }
    }

    var detail: String {
        switch self {
        case .off:
            return "Shows all valid gates without background suppression."
        case .normal:
            return "Removes only high-confidence receiver noise; learned clutter remains in shadow."
        }
    }

    var windowBins: Int {
        switch self {
        case .off:
            return 11
        case .normal:
            return 11
        }
    }

    var staticClutterMinNeighbors: Int {
        switch self {
        case .off:
            return 3
        case .normal:
            return 3
        }
    }

    func apply(to filters: inout RadarFilterSet) {
        filters.noiseFloorEnabled = self != .off
        filters.noiseFloorMethod = "estimated"
        filters.noiseFloorOperation = "mask"
        filters.noiseFloorMarginDb = 0
        filters.receiverNoiseEnabled = self != .off
        filters.receiverNoiseMarginDb = marginDb
        filters.receiverNoiseMinBadMoments = 3
        filters.ciEvidenceEnabled = self != .off
        filters.noiseFloorPercentile = 10
        filters.noiseFloorWindowBins = windowBins
        filters.qcRuntimeMode = .safe
        filters.qcValidatedBundleID = nil
        filters.experimentalLongRangeNoiseEnabled = false
        filters.textureThresholdDb = 10
        filters.textureNearMarginDb = 14
        filters.textureSupportDb = 6
        filters.textureMaxDbz = 30
        filters.textureMinSimilarNeighbors = 1
        filters.staticClutterMinNeighbors = staticClutterMinNeighbors
        filters.staticClutterEnabled = false
        filters.textureCleanupEnabled = false
        filters.companionQcEnabled = false
        // Candidate 8 remains quarantined and shadow-only. Never activate it
        // from a user preset before the release gates pass.
        filters.backgroundModelEnabled = false
        filters.backgroundPersistentFrequencyMin = 0.95
        filters.backgroundMinSamples = 40
        filters.backgroundStaticVradFrequencyMin = 0.80
        filters.backgroundDbzhExcessMaxDb = 3
        filters.backgroundEvidenceScoreThreshold = 3
        filters.backgroundCurrentVradAbsMax = 0.5
        filters.backgroundRequireTrainingDiversity = true
        filters.backgroundMinTrainingDates = 12
        filters.backgroundMinTrainingSpanDays = 90
    }

    static func nearest(to marginDb: Double) -> NoiseCleanupPreset {
        .normal
    }
}

private struct NoiseCleanupAdvancedSheet: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Receiver-noise threshold") {
                    LabeledContent("Method", value: "Estimated profile")
                    HStack {
                        Text("Evidence margin dB")
                        Spacer()
                        Text(String(format: "%.2f dB", model.filters.receiverNoiseMarginDb))
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                    Slider(value: $model.filters.receiverNoiseMarginDb, in: 0...0.5, step: 0.25)
                        .onChange(of: model.filters.receiverNoiseMarginDb) { _ in model.filtersChanged() }
                }
            }
            .navigationTitle("Advanced")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}
