import Foundation
import SwiftUI

struct ContentView: View {
    @StateObject private var model = VisualizerViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                StatusStrip(model: model)
                PPIPlotView(
                    frame: model.frame,
                    opacity: model.filters.opacity,
                    identifyResult: model.identifyResult,
                    onIdentify: { row, column in
                        model.identify(row: row, column: column)
                    }
                )
                .frame(maxWidth: .infinity)
                .frame(height: 360)
                .background(Color(.secondarySystemBackground))

                Divider()

                ScrollView {
                    VStack(spacing: 12) {
                        RadarControlsSection(model: model)
                        FilterSection(model: model)
                        RawCacheSection(model: model)
                    }
                    .padding(12)
                }
                .background(Color(.systemGroupedBackground))
            }
            .navigationTitle("UK WSR")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    Button {
                        Task { await model.loadCatalog() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(model.isLoadingCatalog)
                    .help("Reload catalog")
                }
            }
            .task {
                if model.catalog.isEmpty {
                    await model.loadCatalog()
                }
            }
        }
    }
}

private struct StatusStrip: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                if model.isLoadingCatalog || model.isDownloading || model.isRendering {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(model.statusMessage)
                    .font(.footnote)
                    .lineLimit(2)
                Spacer(minLength: 0)
            }

            if let warning = model.warningMessage {
                Text(warning)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(3)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial)
    }
}

private struct RadarControlsSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Radar Controls", systemImage: "scope")
                .font(.headline)

            Picker("Item", selection: $model.selectedItemID) {
                if model.catalog.isEmpty {
                    Text("No catalog").tag(Optional<String>.none)
                }
                ForEach(model.catalog) { item in
                    Text(item.title).tag(Optional(item.id))
                }
            }
            .pickerStyle(.menu)
            .onChange(of: model.selectedItemID) { _ in
                model.itemSelectionChanged()
            }

            if let item = model.selectedItem {
                HStack {
                    Text(item.validationStatus.capitalized)
                    Spacer()
                    Text(model.selectedSourceSizeText)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            HStack {
                Picker("Pulse", selection: $model.selectedPulse) {
                    ForEach(model.availablePulses, id: \.self) { pulse in
                        Text(pulse).tag(pulse)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: model.selectedPulse) { _ in
                    model.fieldSelectionChanged(resetDataset: true)
                }

                Picker("Time", selection: $model.selectedTime) {
                    ForEach(model.availableTimes, id: \.self) { time in
                        Text(time).tag(time)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: model.selectedTime) { _ in
                    model.fieldSelectionChanged(resetDataset: true)
                }
            }

            HStack {
                Picker("Variable", selection: $model.selectedQuantity) {
                    ForEach(model.availableQuantities, id: \.self) { quantity in
                        Text(quantity).tag(quantity)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: model.selectedQuantity) { _ in
                    model.fieldSelectionChanged(resetDataset: true)
                }

                Picker("Elevation", selection: $model.selectedDataset) {
                    if model.availableDatasets.isEmpty {
                        Text("Auto").tag("")
                    }
                    ForEach(model.availableDatasets) { record in
                        Text(datasetLabel(record)).tag(record.dataset)
                    }
                }
                .pickerStyle(.menu)
                .onChange(of: model.selectedDataset) { _ in
                    model.fieldSelectionChanged()
                }
            }

            Text(model.selectedFieldSummary.isEmpty ? "No field selected" : model.selectedFieldSummary)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .panelStyle()
    }

    private func datasetLabel(_ record: QuantityRecord) -> String {
        if let elevation = record.elevationDeg {
            return "\(String(format: "%.2f", elevation)) deg (\(datasetName(record)))"
        }
        if let height = record.nominalHeightM {
            return "\(Int(height)) m (\(datasetName(record)))"
        }
        return datasetName(record)
    }

    private func datasetName(_ record: QuantityRecord) -> String {
        record.dataset.hasPrefix("dataset") ? record.dataset : "dataset\(record.dataset)"
    }
}

private struct FilterSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Display", systemImage: "slider.horizontal.3")
                .font(.headline)

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
                    OptionalDoubleField(title: "CAPPI m", value: $model.filters.cappiHeightM, onCommit: { model.fieldSelectionChanged() })
                    OptionalDoubleField(title: "Display min", value: $model.filters.displayMin, onCommit: model.filtersChanged)
                }
                GridRow {
                    OptionalDoubleField(title: "Display max", value: $model.filters.displayMax, onCommit: model.filtersChanged)
                    Color.clear.frame(height: 0)
                }
            }

            Toggle(isOn: $model.filters.noiseFloorEnabled) {
                Text("Remove range-dependent noise floor")
                    .font(.caption)
                    .lineLimit(2)
            }
            .onChange(of: model.filters.noiseFloorEnabled) { _ in model.filtersChanged() }

            if model.filters.noiseFloorEnabled {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Margin dB")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Slider(value: $model.filters.noiseFloorMarginDb, in: 0...12, step: 0.5)
                        .onChange(of: model.filters.noiseFloorMarginDb) { _ in model.filtersChanged() }
                }
            }
        }
        .panelStyle()
    }
}

private struct RawCacheSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Raw Cache", systemImage: "externaldrive")
                .font(.headline)

            HStack {
                Text(model.cacheStatus.displayText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Button(role: .destructive) {
                    model.clearCache()
                } label: {
                    Label("Clear Raw Cache", systemImage: "trash")
                }
                .buttonStyle(.bordered)
                .disabled(model.cacheStatus.fileCount == 0 || model.isDownloading || model.isRendering)
            }

            if let frame = model.frame {
                HStack {
                    Text("\(frame.rows)x\(frame.columns)")
                    Text(frame.palette)
                    if let min = frame.stats.scaleMin, let max = frame.stats.scaleMax {
                        Text(String(format: "%.1f to %.1f", min, max))
                    }
                    if frame.noiseFloor.enabled {
                        Text("\(frame.noiseFloor.maskedCount) masked")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .panelStyle()
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

private struct PPIPlotView: View {
    var frame: PPIFrame?
    var opacity: Double
    var identifyResult: IdentifyResult?
    var onIdentify: (Int, Int) -> Void

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .bottomLeading) {
                Canvas { context, size in
                    drawBackground(context: context, size: size)
                    if let frame {
                        drawPPI(frame, context: context, size: size)
                    }
                    drawOverlay(context: context, size: size)
                }
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onEnded { value in
                            guard let frame, let bin = binAt(value.location, size: proxy.size, frame: frame) else { return }
                            onIdentify(bin.row, bin.column)
                        }
                )

                VStack(alignment: .leading, spacing: 2) {
                    if let frame {
                        Text(frame.metadata.radarDisplayLine)
                        Text(frame.metadata.sweepDisplayLine)
                    } else {
                        Text("No source frame")
                        Text("No PPI rendered")
                    }
                    if let identifyResult {
                        Text(identifyResult.compactDescription)
                    }
                }
                .font(.caption2)
                .foregroundStyle(.primary)
                .padding(8)
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .padding(10)
            }
        }
        .accessibilityLabel("PPI radar plot")
    }

    private func drawPPI(_ frame: PPIFrame, context: GraphicsContext, size: CGSize) {
        let radius = plotRadius(size)
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let rows = max(frame.rows, 1)
        let columns = max(frame.columns, 1)
        let angleStep = 360.0 / Double(rows)

        for row in 0..<rows {
            let start = Double(row) * angleStep - 90
            let end = Double(row + 1) * angleStep - 90
            for column in 0..<columns {
                let index = frame.index(row: row, column: column)
                guard frame.valid[index] else { continue }
                let inner = radius * Double(column) / Double(columns)
                let outer = radius * Double(column + 1) / Double(columns)
                var path = Path()
                path.addArc(
                    center: center,
                    radius: outer,
                    startAngle: .degrees(start),
                    endAngle: .degrees(end),
                    clockwise: false
                )
                path.addArc(
                    center: center,
                    radius: inner,
                    startAngle: .degrees(end),
                    endAngle: .degrees(start),
                    clockwise: true
                )
                path.closeSubpath()
                context.fill(path, with: .color(PaletteEngine.color(frame.scaled[index], palette: frame.palette, opacity: opacity)))
            }
        }
    }

    private func drawBackground(context: GraphicsContext, size: CGSize) {
        let rect = CGRect(origin: .zero, size: size)
        context.fill(Path(rect), with: .color(Color(.systemBackground)))
    }

    private func drawOverlay(context: GraphicsContext, size: CGSize) {
        let radius = plotRadius(size)
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        var overlay = Path()
        for fraction in [0.25, 0.5, 0.75, 1.0] {
            overlay.addEllipse(in: CGRect(
                x: center.x - radius * fraction,
                y: center.y - radius * fraction,
                width: radius * 2 * fraction,
                height: radius * 2 * fraction
            ))
        }
        overlay.move(to: CGPoint(x: center.x - radius, y: center.y))
        overlay.addLine(to: CGPoint(x: center.x + radius, y: center.y))
        overlay.move(to: CGPoint(x: center.x, y: center.y - radius))
        overlay.addLine(to: CGPoint(x: center.x, y: center.y + radius))
        context.stroke(overlay, with: .color(Color.secondary.opacity(0.35)), lineWidth: 0.8)
    }

    private func binAt(_ point: CGPoint, size: CGSize, frame: PPIFrame) -> (row: Int, column: Int)? {
        let radius = plotRadius(size)
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let dx = point.x - center.x
        let dy = center.y - point.y
        let distance = hypot(dx, dy)
        guard distance <= radius else { return nil }
        let azimuth = (atan2(dx, dy) * 180 / Double.pi + 360).truncatingRemainder(dividingBy: 360)
        let row = Int((azimuth / 360) * Double(max(frame.rows, 1)))
        let column = Int((distance / radius) * Double(max(frame.columns, 1)))
        return (max(0, min(frame.rows - 1, row)), max(0, min(frame.columns - 1, column)))
    }

    private func plotRadius(_ size: CGSize) -> Double {
        Double(min(size.width, size.height)) * 0.46
    }
}

private extension View {
    func panelStyle() -> some View {
        self
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private extension RadarGridMetadata {
    var radarDisplayLine: String {
        "\(radar) \(date) \(quantity)"
    }

    var sweepDisplayLine: String {
        let elevation = elevationDeg.map { String(format: "%.1f deg", $0) } ?? "elevation n/a"
        return "\(pulse) \(time) \(dataset) \(elevation)"
    }
}
