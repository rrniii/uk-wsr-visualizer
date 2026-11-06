import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct FilterSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader("Display", systemImage: "slider.horizontal.3")

            HStack {
                Picker("Palette", selection: $model.filters.palette) {
                    ForEach(PaletteEngine.paletteNames, id: \.self) { name in
                        Text(PaletteEngine.displayName(for: name)).tag(name)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: model.filters.palette) { _ in model.filtersChanged() }

                VStack(alignment: .leading, spacing: 2) {
                    Text("Opacity")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Slider(value: $model.filters.opacity, in: 0.2...1.0)
                        .onChange(of: model.filters.opacity) { _ in model.filtersChanged() }
                }
            }

            Toggle(isOn: $model.showDetailedIdentifyReadout) {
                Text("Detailed tap readout")
                    .font(.caption)
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Colour limits")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Picker("Colour limits", selection: displayRangeModeBinding) {
                        ForEach(DisplayRangeMode.allCases) { mode in
                            Text(mode.displayName).tag(mode)
                        }
                    }
                    .pickerStyle(.menu)
                }

                Text(displayRangeDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    OptionalDoubleField(title: "Min km", value: $model.filters.minRangeKm, onCommit: model.filtersChanged)
                    OptionalDoubleField(title: "Max km", value: $model.filters.maxRangeKm, onCommit: model.filtersChanged)
                }
                GridRow {
                    OptionalDoubleField(title: "Min az", value: $model.filters.minAzimuthDeg, onCommit: model.filtersChanged)
                    OptionalDoubleField(title: "Max az", value: $model.filters.maxAzimuthDeg, onCommit: model.filtersChanged)
                }
                GridRow {
                    OptionalDoubleField(title: "Min value", value: $model.filters.minValue, onCommit: model.filtersChanged)
                    OptionalDoubleField(title: "Max value", value: $model.filters.maxValue, onCommit: model.filtersChanged)
                }
                GridRow {
                    OptionalDoubleField(title: "Height slice m", value: $model.filters.cappiHeightM, onCommit: model.filtersChanged)
                    Color.clear.frame(height: 0)
                }
            }
            Text("Within ±250 m of the height above sea level; no interpolation.")
                .font(.caption)
                .foregroundStyle(.secondary)

            if model.filters.displayRangeMode == .custom {
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                    GridRow {
                        OptionalDoubleField(title: "Display min", value: $model.filters.displayMin, onCommit: model.filtersChanged)
                        OptionalDoubleField(title: "Display max", value: $model.filters.displayMax, onCommit: model.filtersChanged)
                    }
                }

                Button {
                    model.filters.displayMin = nil
                    model.filters.displayMax = nil
                    model.filtersChanged()
                } label: {
                    Label("Reset custom limits", systemImage: "arrow.counterclockwise")
                }
                .buttonStyle(.bordered)
            }

        }
        .panelStyle()
    }

    private var displayRangeModeBinding: Binding<DisplayRangeMode> {
        Binding(
            get: { model.filters.displayRangeMode },
            set: { mode in
                model.filters.displayRangeMode = mode
                if mode != .custom {
                    model.filters.displayMin = nil
                    model.filters.displayMax = nil
                }
                model.filtersChanged()
            }
        )
    }

    private var displayRangeDescription: String {
        let quantity = model.frame?.metadata.quantity ?? model.selectedQuantity
        guard !quantity.isEmpty else {
            return model.filters.displayRangeMode.detail
        }

        switch model.filters.displayRangeMode {
        case .standard:
            let display = DisplayConfig.forQuantity(quantity, requestedPalette: model.filters.palette)
            guard let min = display.scaleMin, let max = display.scaleMax else {
                return "\(quantity): data stretch is used because no standard limits are known."
            }
            let unit = quantityUnit(quantity)
            return "\(quantity): \(formatLimit(min, unit: unit)) to \(formatLimit(max, unit: unit))"
        case .dataStretch:
            return DisplayRangeMode.dataStretch.detail
        case .custom:
            return DisplayRangeMode.custom.detail
        }
    }

    private func formatLimit(_ value: Double, unit: String) -> String {
        let formatted: String
        if abs(value) >= 10 {
            formatted = String(format: "%.0f", value)
        } else {
            formatted = String(format: "%.2g", value)
        }
        return unit.isEmpty ? formatted : "\(formatted) \(unit)"
    }
}

private struct OptionalDoubleField: View {
    var title: String
    @Binding var value: Double?
    var onCommit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("", text: Binding(
                get: {
                    guard let value else { return "" }
                    return String(format: "%.3g", value)
                },
                set: { text in
                    value = Double(text.trimmingCharacters(in: .whitespacesAndNewlines))
                }
            ))
            .keyboardType(.numbersAndPunctuation)
            .textFieldStyle(.roundedBorder)
            .onSubmit(onCommit)
        }
    }
}
