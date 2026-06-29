import Foundation
import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var model = VisualizerViewModel()

    var body: some View {
        ZStack {
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
                            MetadataSection(model: model)
                            ExportSection(model: model)
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

            if model.shouldShowLaunchLoadingScreen {
                LaunchLoadingView()
                    .transition(.opacity)
                    .zIndex(1)
            }
        }
        .animation(.easeOut(duration: 0.25), value: model.shouldShowLaunchLoadingScreen)
    }
}

private struct LaunchLoadingView: View {
    var body: some View {
        GeometryReader { proxy in
            let iconSide = min(proxy.size.width, proxy.size.height) * 0.78

            ZStack {
                Color("LaunchBackground")
                    .ignoresSafeArea()

                VStack(spacing: 28) {
                    Image("LaunchIcon")
                        .resizable()
                        .scaledToFit()
                        .frame(width: iconSide, height: iconSide)
                        .accessibilityLabel("UK WSR")

                    ProgressView()
                        .tint(.white)
                        .controlSize(.regular)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
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
    @State private var isShowingCatalogSearch = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Radar Controls", systemImage: "scope")
                .font(.headline)

            Button {
                isShowingCatalogSearch = true
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass")
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Item")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(model.selectedItem?.title ?? "No item selected")
                            .lineLimit(1)
                    }
                    Spacer()
                    Text(model.catalogSearchSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.bordered)
            .disabled(model.catalog.isEmpty)
            .sheet(isPresented: $isShowingCatalogSearch) {
                CatalogSearchView(model: model)
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
                    if model.availablePulses.isEmpty {
                        Text("No pulses").tag("")
                    }
                    ForEach(model.availablePulses, id: \.self) { pulse in
                        Text(pulse).tag(pulse)
                    }
                }
                .pickerStyle(.menu)
                .disabled(model.availablePulses.isEmpty)
                .onChange(of: model.selectedPulse) { _ in
                    model.fieldSelectionChanged(resetDataset: true)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Picker("Time", selection: $model.selectedTime) {
                        if model.availableTimes.isEmpty {
                            Text("No times").tag("")
                        }
                        ForEach(model.availableTimes, id: \.self) { time in
                            Text(time).tag(time)
                        }
                    }
                    .pickerStyle(.menu)
                    .disabled(model.availableTimes.isEmpty)
                    .onChange(of: model.selectedTime) { _ in
                        model.fieldSelectionChanged(resetDataset: true)
                    }

                    HStack(spacing: 8) {
                        Button {
                            model.stepTime(by: -1)
                        } label: {
                            Image(systemName: "chevron.left")
                        }
                        .disabled(!model.canStepTime || model.isRendering || model.isDownloading)

                        Text(model.selectedTimePositionText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                            .frame(minWidth: 42)

                        Button {
                            model.stepTime(by: 1)
                        } label: {
                            Image(systemName: "chevron.right")
                        }
                        .disabled(!model.canStepTime || model.isRendering || model.isDownloading)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }

            HStack {
                Picker("Variable", selection: $model.selectedQuantity) {
                    if model.availableQuantities.isEmpty {
                        Text("No variables").tag("")
                    }
                    ForEach(model.availableQuantities, id: \.self) { quantity in
                        Text(quantity).tag(quantity)
                    }
                }
                .pickerStyle(.menu)
                .disabled(model.availableQuantities.isEmpty)
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

            if let availability = model.selectedFieldAvailabilityText {
                Text(availability)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(2)
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
        record.datasetName
    }
}

private struct CatalogSearchView: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("Catalog Search") {
                    Picker("Radar", selection: criteriaBinding(\.radar)) {
                        Text("Any").tag("")
                        ForEach(model.catalogRadarOptions, id: \.self) { radar in
                            Text(model.radarDisplayName(radar)).tag(radar)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack(spacing: 10) {
                        CatalogDateField(title: "Start Date", text: criteriaBinding(\.startDate))
                        CatalogDateField(title: "End Date", text: criteriaBinding(\.endDate))
                    }

                    Picker("Pulse", selection: criteriaBinding(\.pulse)) {
                        Text("Any").tag("")
                        ForEach(model.catalogPulseOptions, id: \.self) { pulse in
                            Text(pulse).tag(pulse)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack {
                        Button {
                            model.setCatalogSearchToFirstDay()
                        } label: {
                            Label("First day", systemImage: "backward.end")
                        }
                        .disabled(model.catalogDateRange == nil)

                        Button {
                            model.setCatalogSearchToLatestDay()
                        } label: {
                            Label("Latest day", systemImage: "forward.end")
                        }
                        .disabled(model.catalogDateRange == nil)
                    }
                    .buttonStyle(.bordered)

                    Text(model.catalogCoverageStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Section {
                    if model.filteredCatalogItems.isEmpty {
                        Text("No matching items")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(model.filteredCatalogItems) { item in
                        Button {
                            model.selectCatalogItem(item)
                            dismiss()
                        } label: {
                            CatalogSearchRow(item: item, isSelected: model.selectedItemID == item.id)
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    Text(model.catalogSearchSummary)
                }
            }
            .searchable(text: criteriaBinding(\.text), prompt: "Search catalog")
            .navigationTitle("Catalog Search")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button {
                        model.resetCatalogSearch()
                    } label: {
                        Image(systemName: "arrow.counterclockwise")
                    }
                    .help("Reset catalog search")
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .task {
            await model.loadCoverageForCurrentSearch()
        }
        .onChange(of: model.catalogSearch) { _ in
            Task { await model.loadCoverageForCurrentSearch() }
        }
    }

    private func criteriaBinding<Value>(_ keyPath: WritableKeyPath<CatalogSearchCriteria, Value>) -> Binding<Value> {
        Binding(
            get: { model.catalogSearch[keyPath: keyPath] },
            set: { model.catalogSearch[keyPath: keyPath] = $0 }
        )
    }
}

private struct CatalogDateField: View {
    var title: String
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("YYYY-MM-DD", text: $text)
                .keyboardType(.numbersAndPunctuation)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        }
    }
}

private struct CatalogSearchRow: View {
    var item: CatalogItem
    var isSelected: Bool

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(detailLine)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Text(facetLine)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            if isSelected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.tint)
            }
        }
        .contentShape(Rectangle())
        .padding(.vertical, 4)
    }

    private var detailLine: String {
        [
            item.radarNum.isEmpty ? nil : item.radarNum,
            item.validationStatus.isEmpty ? nil : item.validationStatus.capitalized,
            item.sourceType == "raw_volume_day" ? "Raw volume day" : "Aggregate day",
        ]
        .compactMap { $0 }
        .joined(separator: ", ")
    }

    private var facetLine: String {
        let pulseText = item.pulses.isEmpty ? "Any pulse" : item.pulses.prefix(4).joined(separator: ", ")
        let quantityText = item.quantities.isEmpty ? "No variables" : item.quantities.prefix(4).joined(separator: ", ")
        return "\(pulseText) / \(quantityText)"
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

private struct MetadataSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var didCopySourceURL = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Metadata", systemImage: "doc.text.magnifyingglass")
                .font(.headline)

            if model.selectedSourceDiagnosticRows.isEmpty {
                Text("No item selected")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.selectedSourceDiagnosticRows) { row in
                    HStack(alignment: .firstTextBaseline) {
                        Text(row.label)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(width: 82, alignment: .leading)
                        Text(row.value)
                            .font(.caption)
                            .lineLimit(2)
                        Spacer(minLength: 0)
                    }
                }

                if !model.selectedSourceURLString.isEmpty {
                    Button {
                        UIPasteboard.general.string = model.selectedSourceURLString
                        didCopySourceURL = true
                    } label: {
                        Label(didCopySourceURL ? "Copied Source URL" : "Copy Source URL", systemImage: "doc.on.doc")
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .panelStyle()
        .onChange(of: model.selectedSourceURLString) { _ in
            didCopySourceURL = false
        }
    }
}

private struct ExportSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var exportedPNGURL: URL?
    @State private var exportMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Export", systemImage: "square.and.arrow.up")
                .font(.headline)

            HStack {
                Button {
                    createPNG()
                } label: {
                    Label("Create PNG", systemImage: "photo")
                }
                .buttonStyle(.bordered)
                .disabled(model.frame == nil)

                if let exportedPNGURL {
                    ShareLink(item: exportedPNGURL) {
                        Label("Share PNG", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }

            if let exportMessage {
                Text(exportMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .panelStyle()
        .onChange(of: model.frame?.id) { _ in
            exportedPNGURL = nil
            exportMessage = nil
        }
    }

    private func createPNG() {
        guard let frame = model.frame else {
            exportMessage = "No rendered PPI"
            return
        }
        do {
            exportedPNGURL = try PPIImageExporter.writePNG(frame: frame, opacity: model.filters.opacity)
            exportMessage = "PNG ready"
        } catch {
            exportedPNGURL = nil
            exportMessage = error.localizedDescription
        }
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

private enum PPIImageExportError: LocalizedError {
    case noPNGData

    var errorDescription: String? {
        "Could not create PNG data for the rendered PPI."
    }
}

private struct PPIImageExporter {
    static func writePNG(frame: PPIFrame, opacity: Double, size: CGSize = CGSize(width: 1200, height: 1200)) throws -> URL {
        let rendererFormat = UIGraphicsImageRendererFormat.default()
        rendererFormat.scale = 1
        let renderer = UIGraphicsImageRenderer(size: size, format: rendererFormat)
        let image = renderer.image { context in
            draw(frame: frame, opacity: opacity, in: context.cgContext, size: size)
        }
        guard let data = image.pngData() else {
            throw PPIImageExportError.noPNGData
        }

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(fileName(for: frame))
            .appendingPathExtension("png")
        try? FileManager.default.removeItem(at: fileURL)
        try data.write(to: fileURL, options: .atomic)
        return fileURL
    }

    private static func draw(frame: PPIFrame, opacity: Double, in context: CGContext, size: CGSize) {
        let rect = CGRect(origin: .zero, size: size)
        UIColor.systemBackground.setFill()
        context.fill(rect)

        let radius = min(size.width, size.height) * 0.46
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let rows = max(frame.rows, 1)
        let columns = max(frame.columns, 1)
        let angleStep = 360.0 / Double(rows)

        for row in 0..<rows {
            let start = CGFloat((Double(row) * angleStep - 90) * Double.pi / 180)
            let end = CGFloat((Double(row + 1) * angleStep - 90) * Double.pi / 180)
            for column in 0..<columns {
                let index = frame.index(row: row, column: column)
                guard frame.valid[index] else { continue }
                let inner = radius * CGFloat(column) / CGFloat(columns)
                let outer = radius * CGFloat(column + 1) / CGFloat(columns)
                let rgba = PaletteEngine.rgba(frame.scaled[index], palette: frame.palette, opacity: opacity)
                UIColor(
                    red: rgba.red / 255,
                    green: rgba.green / 255,
                    blue: rgba.blue / 255,
                    alpha: rgba.alpha
                ).setFill()

                let path = UIBezierPath()
                path.addArc(withCenter: center, radius: outer, startAngle: start, endAngle: end, clockwise: true)
                path.addArc(withCenter: center, radius: inner, startAngle: end, endAngle: start, clockwise: false)
                path.close()
                path.fill()
            }
        }

        UIColor.secondaryLabel.withAlphaComponent(0.35).setStroke()
        for fraction in [0.25, 0.5, 0.75, 1.0] {
            let ringRadius = radius * CGFloat(fraction)
            let ring = UIBezierPath(ovalIn: CGRect(
                x: center.x - ringRadius,
                y: center.y - ringRadius,
                width: ringRadius * 2,
                height: ringRadius * 2
            ))
            ring.lineWidth = 2
            ring.stroke()
        }

        let crosshair = UIBezierPath()
        crosshair.move(to: CGPoint(x: center.x - radius, y: center.y))
        crosshair.addLine(to: CGPoint(x: center.x + radius, y: center.y))
        crosshair.move(to: CGPoint(x: center.x, y: center.y - radius))
        crosshair.addLine(to: CGPoint(x: center.x, y: center.y + radius))
        crosshair.lineWidth = 2
        crosshair.stroke()
    }

    private static func fileName(for frame: PPIFrame) -> String {
        let raw = [
            "uk-wsr",
            frame.metadata.radar,
            frame.metadata.date,
            frame.metadata.pulse,
            frame.metadata.time,
            frame.metadata.quantity,
            frame.metadata.dataset,
        ]
        .filter { !$0.isEmpty }
        .joined(separator: "-")
        return raw.map { character in
            character.isLetter || character.isNumber || character == "-" ? character : "-"
        }
        .reduce(into: "") { output, character in
            output.append(character)
        }
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
