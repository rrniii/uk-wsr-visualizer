import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct RadarControlsSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var isShowingCatalogSearch = false
    @State private var isShowingTimeSelector = false

    var body: some View {
        VStack(alignment: .leading, spacing: AppUI.sectionSpacing) {
            PanelHeader("Radar", systemImage: "scope") {
                if model.isRendering {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            Button {
                isShowingCatalogSearch = true
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "list.bullet.rectangle")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(.blue)
                        .frame(width: 24, height: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("DATA")
                            .font(AppUI.labelFont)
                            .foregroundStyle(.secondary)
                        Text(model.selectedItem?.title ?? "No data selected")
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
                .overlay(
                    RoundedRectangle(cornerRadius: AppUI.tileRadius)
                        .stroke(AppUI.hairline, lineWidth: 1)
                )
            }
            .buttonStyle(.plain)
            .disabled(model.catalog.isEmpty)
            .accessibilityIdentifier("CatalogItemButton")
            .sheet(isPresented: $isShowingCatalogSearch) {
                CatalogSearchView(model: model)
            }

            VStack(spacing: AppUI.controlSpacing) {
                DataSelectorMenu(
                    title: "Pulse",
                    value: pulseValueText,
                    systemImage: "waveform.path.ecg",
                    isEnabled: !model.availablePulses.isEmpty && !isFieldControlDisabled
                ) {
                    if model.availablePulses.isEmpty {
                        Text("No pulses")
                    }
                    ForEach(model.availablePulses, id: \.self) { pulse in
                        SelectableMenuButton(title: pulse, isSelected: pulse == model.selectedPulse) {
                            model.selectPulse(pulse)
                        }
                    }
                }
                .accessibilityIdentifier("PulseSelectorButton")

                HStack(spacing: 8) {
                    TimeStepButton(systemImage: "chevron.left", accessibilityLabel: "Previous time") {
                        model.stepTime(by: -1)
                    }
                    .disabled(!model.canStepTime || isFieldControlDisabled)

                    Button {
                        isShowingTimeSelector = true
                    } label: {
                        ControlTile(
                            title: "Time",
                            value: timeValueText,
                            systemImage: "clock"
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(model.availableTimes.isEmpty || isFieldControlDisabled)
                    .accessibilityIdentifier("TimeSelectorButton")
                    .sheet(isPresented: $isShowingTimeSelector) {
                        TimeSelectionView(model: model)
                    }

                    TimeStepButton(systemImage: "chevron.right", accessibilityLabel: "Next time") {
                        model.stepTime(by: 1)
                    }
                    .disabled(!model.canStepTime || isFieldControlDisabled)
                }

                HStack(spacing: 8) {
                    DataSelectorMenu(
                        title: "Variable",
                        value: variableValueText,
                        systemImage: "aqi.medium",
                        isEnabled: !model.availableQuantities.isEmpty && !isFieldControlDisabled
                    ) {
                        if model.availableQuantities.isEmpty {
                            Text(model.canAutoSelectFileQuantity ? "Auto" : "No variables")
                        }
                        ForEach(model.availableQuantities, id: \.self) { quantity in
                            SelectableMenuButton(title: quantity, isSelected: quantity == model.selectedQuantity) {
                                model.selectQuantity(quantity)
                            }
                        }
                    }
                    .accessibilityIdentifier("VariableSelectorButton")

                    DataSelectorMenu(
                        title: "Elevation",
                        value: elevationValueText,
                        systemImage: "angle",
                        isEnabled: !model.availableDatasets.isEmpty && !isFieldControlDisabled
                    ) {
                        if model.availableDatasets.isEmpty {
                            Text("Auto")
                        }
                        ForEach(model.availableDatasets) { record in
                            let label = datasetLabel(record)
                            SelectableMenuButton(title: label, isSelected: record.dataset == model.selectedDataset) {
                                model.selectDataset(record.dataset)
                            }
                        }
                    }
                    .accessibilityIdentifier("ElevationSelectorButton")
                }

                NoiseFloorControlsBlock(model: model)
            }

            if let availability = model.selectedFieldAvailabilityText {
                Text(availability)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(2)
            }
        }
        .panelStyle()
    }

    private func datasetLabel(_ record: QuantityRecord) -> String {
        if let elevation = record.elevationDeg {
            return "\(String(format: "%.2f", elevation))°"
        }
        if let height = record.nominalHeightM {
            return "\(Int(height)) m"
        }
        return "Elevation n/a"
    }

    private var isFieldControlDisabled: Bool {
        model.isExportingVideo
    }

    private var pulseValueText: String {
        model.availablePulses.isEmpty ? "No pulses" : (model.selectedPulse.isEmpty ? "Auto" : model.selectedPulse)
    }

    private var timeValueText: String {
        guard !model.availableTimes.isEmpty else { return "No times" }
        let time = model.selectedTime.isEmpty ? "Auto" : model.selectedTime
        return "\(time) · \(model.selectedTimePositionText)"
    }

    private var variableValueText: String {
        guard !model.availableQuantities.isEmpty else {
            return model.canAutoSelectFileQuantity ? "Auto" : "No variables"
        }
        return model.selectedQuantity.isEmpty ? "Auto" : model.selectedQuantity
    }

    private var elevationValueText: String {
        model.availableDatasets.isEmpty ? "Auto" : model.selectedElevationText
    }
}

private struct TimeSelectionView: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(model.availableTimes, id: \.self) { time in
                Button {
                    model.selectTime(time)
                    dismiss()
                } label: {
                    HStack {
                        Text(model.timeDisplayText(time))
                            .monospacedDigit()
                        Spacer()
                        if time == model.selectedTime {
                            Image(systemName: "checkmark")
                                .font(.body.weight(.semibold))
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("TimeOption-\(time)")
            }
            .navigationTitle("Select Time")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct DataSelectorMenu<Content: View>: View {
    var title: String
    var value: String
    var systemImage: String
    var isEnabled: Bool
    var content: () -> Content

    init(
        title: String,
        value: String,
        systemImage: String,
        isEnabled: Bool = true,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.value = value
        self.systemImage = systemImage
        self.isEnabled = isEnabled
        self.content = content
    }

    var body: some View {
        Menu {
            content()
        } label: {
            ControlTile(title: title, value: value, systemImage: systemImage)
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.6)
    }
}

private struct SelectableMenuButton: View {
    var title: String
    var isSelected: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            if isSelected {
                Label(title, systemImage: "checkmark")
            } else {
                Text(title)
            }
        }
    }
}

private struct TimeStepButton: View {
    var systemImage: String
    var accessibilityLabel: String
    var action: () -> Void

    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.headline)
                .frame(width: 52, height: AppUI.tileHeight)
                .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
                .overlay(
                    RoundedRectangle(cornerRadius: AppUI.tileRadius)
                        .stroke(AppUI.hairline, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .opacity(isEnabled ? 1 : 0.45)
        .accessibilityLabel(accessibilityLabel)
    }
}
