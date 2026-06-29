import AVFoundation
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
                    Group {
                        if AppRuntime.isUITesting {
                            LightweightPPIPlotView(frame: model.frame, identifyResult: model.identifyResult)
                        } else {
                            PPIPlotView(
                                frame: model.frame,
                                opacity: model.filters.opacity,
                                mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                                mapOpacity: model.mapSettings.opacity,
                                identifyResult: model.identifyResult,
                                onIdentify: { row, column in
                                    model.identify(row: row, column: column)
                                }
                            )
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 360)
                    .background(Color(.secondarySystemBackground))
                    .accessibilityIdentifier("PPIPlotView")

                    Divider()

                    ScrollView {
                        VStack(spacing: 12) {
                            RadarControlsSection(model: model)
                            MapSection(model: model)
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
                .onChange(of: model.frame?.id) { _ in
                    guard !model.isExportingVideo else { return }
                    Task { await model.refreshMapSnapshot(force: true) }
                }
            }

            if model.shouldShowLaunchLoadingScreen {
                LaunchLoadingView()
                    .transition(.opacity)
                    .zIndex(1)
                    .accessibilityIdentifier("LaunchLoadingView")
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
                    .accessibilityIdentifier("StatusMessage")
                Spacer(minLength: 0)
            }

            if let warning = model.warningMessage {
                Text(warning)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(3)
                    .accessibilityIdentifier("WarningMessage")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial)
        .accessibilityIdentifier("StatusStrip")
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
            .accessibilityIdentifier("CatalogItemButton")
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

            VStack(spacing: 8) {
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
                            model.selectedPulse = pulse
                            model.fieldSelectionChanged(resetDataset: true)
                        }
                    }
                }
                .accessibilityIdentifier("PulseSelectorButton")

                HStack(spacing: 8) {
                    TimeStepButton(systemImage: "chevron.left", accessibilityLabel: "Previous time") {
                        model.stepTime(by: -1)
                    }
                    .disabled(!model.canStepTime || isFieldControlDisabled)

                    DataSelectorMenu(
                        title: "Time",
                        value: timeValueText,
                        systemImage: "clock",
                        isEnabled: !model.availableTimes.isEmpty && !isFieldControlDisabled
                    ) {
                        if model.availableTimes.isEmpty {
                            Text("No times")
                        }
                        ForEach(model.availableTimes, id: \.self) { time in
                            SelectableMenuButton(title: time, isSelected: time == model.selectedTime) {
                                model.selectedTime = time
                                model.fieldSelectionChanged(resetDataset: true)
                            }
                        }
                    }
                    .accessibilityIdentifier("TimeSelectorButton")

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
                                model.selectedQuantity = quantity
                                model.fieldSelectionChanged(resetDataset: true)
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
                                model.selectedDataset = record.dataset
                                model.fieldSelectionChanged()
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

            Text(model.selectedFieldSummary.isEmpty ? "No field selected" : model.selectedFieldSummary)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
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
        model.isRendering || model.isDownloading
    }

    private var pulseValueText: String {
        model.availablePulses.isEmpty ? "No pulses" : (model.selectedPulse.isEmpty ? "Auto" : model.selectedPulse)
    }

    private var timeValueText: String {
        guard !model.availableTimes.isEmpty else { return "No times" }
        let time = model.selectedTime.isEmpty ? "Auto" : model.selectedTime
        return "\(time) - \(model.selectedTimePositionText)"
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
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(value)
                        .font(.body)
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background(Color(.tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color(.separator).opacity(0.35), lineWidth: 1)
            )
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
                .frame(width: 48, height: 56)
                .background(Color(.tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color(.separator).opacity(0.35), lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .opacity(isEnabled ? 1 : 0.45)
        .accessibilityLabel(accessibilityLabel)
    }
}

private struct NoiseFloorControlsBlock: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(isOn: $model.filters.noiseFloorEnabled) {
                Text("Remove range-dependent noise floor")
                    .font(.caption)
                    .lineLimit(2)
            }
            .onChange(of: model.filters.noiseFloorEnabled) { _ in model.filtersChanged() }

            if model.filters.noiseFloorEnabled {
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Method")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("Estimated profile")
                            .font(.caption)
                            .lineLimit(1)
                    }
                    .frame(width: 120, alignment: .leading)

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Margin dB")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Slider(value: $model.filters.noiseFloorMarginDb, in: 0...12, step: 0.5)
                            .onChange(of: model.filters.noiseFloorMarginDb) { _ in model.filtersChanged() }
                    }
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color(.separator).opacity(0.35), lineWidth: 1)
        )
    }
}

private struct MapSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Map", systemImage: "map")
                .font(.headline)

            Toggle(isOn: mapEnabledBinding) {
                Text("Map underlay")
            }
            .disabled(model.frame == nil || model.isRendering || model.isDownloading || model.isExportingVideo)

            HStack(spacing: 10) {
                Picker("Style", selection: mapStyleBinding) {
                    ForEach(MapUnderlayStyle.allCases) { style in
                        Text(style.displayName).tag(style)
                    }
                }
                .pickerStyle(.menu)
                .disabled(!model.mapSettings.isEnabled || model.isLoadingMapSnapshot)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Map opacity")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Slider(value: mapOpacityBinding, in: 0.15...0.85)
                        .disabled(!model.mapSettings.isEnabled)
                }
            }

            HStack {
                if model.isLoadingMapSnapshot {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(model.mapStatusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Spacer()
                Button {
                    Task { await model.refreshMapSnapshot(force: true) }
                } label: {
                    Label("Reload Map", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .disabled(!model.mapSettings.isEnabled || model.frame == nil || model.isLoadingMapSnapshot)
            }
        }
        .panelStyle()
    }

    private var mapEnabledBinding: Binding<Bool> {
        Binding(
            get: { model.mapSettings.isEnabled },
            set: { newValue in
                model.mapSettings.isEnabled = newValue
                Task { await model.refreshMapSnapshot(force: true) }
            }
        )
    }

    private var mapStyleBinding: Binding<MapUnderlayStyle> {
        Binding(
            get: { model.mapSettings.style },
            set: { newValue in
                model.mapSettings.style = newValue
                Task { await model.refreshMapSnapshot(force: true) }
            }
        )
    }

    private var mapOpacityBinding: Binding<Double> {
        Binding(
            get: { model.mapSettings.opacity },
            set: { model.mapSettings.opacity = $0 }
        )
    }
}

private struct CatalogSearchView: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("Quick Actions") {
                    HStack(spacing: 8) {
                        Button {
                            Task {
                                if await model.selectNearestRadarLatest() {
                                    dismiss()
                                }
                            }
                        } label: {
                            Label("Nearest latest", systemImage: "location.fill")
                        }

                        Button {
                            if model.selectLatestUploadedDay() {
                                dismiss()
                            }
                        } label: {
                            Label("Latest uploaded", systemImage: "clock.arrow.circlepath")
                        }
                    }
                    .buttonStyle(.bordered)

                    Button {
                        model.setCatalogSearchToCurrentRadar()
                    } label: {
                        Label("Current radar", systemImage: "scope")
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.selectedItem == nil)
                }

                if !model.recentSelections.isEmpty {
                    Section("Recent") {
                        ForEach(Array(model.recentSelections.prefix(5))) { recent in
                            Button {
                                if model.applyRecentSelection(recent) {
                                    dismiss()
                                }
                            } label: {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(recent.title)
                                        .foregroundStyle(.primary)
                                        .lineLimit(1)
                                    Text(recent.detailText.isEmpty ? "Auto field selection" : recent.detailText)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
                    }
                }

                Section("Filters") {
                    Picker("Radar", selection: criteriaBinding(\.radar)) {
                        Text("Any").tag("")
                        ForEach(model.catalogRadarOptions, id: \.self) { radar in
                            Text(model.radarDisplayName(radar)).tag(radar)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Year", selection: criteriaBinding(\.year)) {
                        Text("Any").tag("")
                        ForEach(model.catalogYearOptions, id: \.self) { year in
                            Text(year).tag(year)
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

                        Button {
                            model.clearCatalogDateFilters()
                        } label: {
                            Label("Clear dates", systemImage: "xmark.circle")
                        }
                    }
                    .buttonStyle(.bordered)

                    Text(model.catalogCoverageStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Section {
                    if model.isLoadingCoverage {
                        ProgressView("Loading coverage")
                    }
                    if model.filteredCatalogItems.isEmpty {
                        Text("No matching items")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(model.filteredCatalogItems) { item in
                        Button {
                            model.selectCatalogItem(item)
                            dismiss()
                        } label: {
                            CatalogSearchRow(
                                item: item,
                                isSelected: model.selectedItemID == item.id,
                                detailLine: model.catalogRowDetailText(for: item),
                                facetLine: model.catalogRowFacetText(for: item),
                                badges: model.catalogRowBadges(for: item)
                            )
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("CatalogSearchRow-\(item.id)")
                    }
                } header: {
                    Text(model.catalogSearchSummary)
                }
            }
            .searchable(text: criteriaBinding(\.text), prompt: "Search catalog")
            .accessibilityIdentifier("CatalogSearchList")
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
                    .accessibilityIdentifier("CatalogSearchDoneButton")
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
                .accessibilityIdentifier("Catalog\(title.replacingOccurrences(of: " ", with: ""))Field")
        }
    }
}

private struct CatalogSearchRow: View {
    var item: CatalogItem
    var isSelected: Bool
    var detailLine: String
    var facetLine: String
    var badges: [String]

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
                if !badges.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 4) {
                            ForEach(badges, id: \.self) { badge in
                                Text(badge)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 6))
                            }
                        }
                    }
                    .scrollDisabled(true)
                }
            }
            Spacer()
            if isSelected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.tint)
            }
        }
        .contentShape(Rectangle())
        .padding(.vertical, 4)
        .accessibilityIdentifier("CatalogSearchRow-\(item.id)")
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
    @State private var exportedVideoURL: URL?
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

                Button {
                    createVideo()
                } label: {
                    Label("Create MP4", systemImage: "film")
                }
                .buttonStyle(.bordered)
                .disabled(model.frame == nil || model.availableTimes.count < 2 || model.isExportingVideo)

                if let exportedPNGURL {
                    ShareLink(item: exportedPNGURL) {
                        Label("Share PNG", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }

                if let exportedVideoURL {
                    ShareLink(item: exportedVideoURL) {
                        Label("Share MP4", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }

            if model.isExportingVideo {
                ProgressView(model.videoExportProgress)
                    .font(.caption)
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
            exportedVideoURL = nil
            exportMessage = nil
        }
    }

    private func createPNG() {
        guard let frame = model.frame else {
            exportMessage = "No rendered PPI"
            return
        }
        do {
            exportedPNGURL = try PPIImageExporter.writePNG(
                frame: frame,
                opacity: model.filters.opacity,
                mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                mapOpacity: model.mapSettings.opacity
            )
            exportMessage = "PNG ready"
        } catch {
            exportedPNGURL = nil
            exportMessage = error.localizedDescription
        }
    }

    private func createVideo() {
        exportedVideoURL = nil
        exportMessage = nil
        Task {
            do {
                if model.mapSettings.isEnabled && model.mapSnapshotImage == nil {
                    await model.refreshMapSnapshot()
                }
                let frames = try await model.renderVideoFramesForCurrentSelection()
                exportedVideoURL = try PPIImageExporter.writeMP4(
                    frames: frames,
                    opacity: model.filters.opacity,
                    mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                    mapOpacity: model.mapSettings.opacity
                )
                exportMessage = "MP4 ready, \(frames.count) frame\(frames.count == 1 ? "" : "s")"
            } catch {
                exportedVideoURL = nil
                exportMessage = error.localizedDescription
            }
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
    var mapUnderlay: UIImage?
    var mapOpacity: Double
    var identifyResult: IdentifyResult?
    var onIdentify: (Int, Int) -> Void

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .bottomLeading) {
                Canvas { context, size in
                    drawBackground(context: context, size: size)
                    if let mapUnderlay {
                        drawMapUnderlay(mapUnderlay, context: context, size: size)
                    }
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

    private func drawMapUnderlay(_ image: UIImage, context: GraphicsContext, size: CGSize) {
        let mapRect = CGRect(origin: .zero, size: size)
        let resolved = context.resolve(Image(uiImage: image))
        var mapContext = context
        mapContext.opacity = mapOpacity
        mapContext.draw(resolved, in: mapRect)
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

private struct LightweightPPIPlotView: View {
    var frame: PPIFrame?
    var identifyResult: IdentifyResult?

    var body: some View {
        GeometryReader { proxy in
            let side = min(proxy.size.width, proxy.size.height) * 0.92

            ZStack(alignment: .bottomLeading) {
                Color(.systemBackground)

                ZStack {
                    ForEach([0.25, 0.5, 0.75, 1.0], id: \.self) { fraction in
                        Circle()
                            .stroke(Color.secondary.opacity(0.35), lineWidth: 0.8)
                            .frame(width: side * fraction, height: side * fraction)
                    }
                    Rectangle()
                        .fill(Color.secondary.opacity(0.35))
                        .frame(width: side, height: 0.8)
                    Rectangle()
                        .fill(Color.secondary.opacity(0.35))
                        .frame(width: 0.8, height: side)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

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
}

private enum PPIImageExportError: LocalizedError {
    case noPNGData
    case noFrames
    case cannotCreatePixelBuffer
    case videoWriterFailed(String)

    var errorDescription: String? {
        switch self {
        case .noPNGData:
            return "Could not create PNG data for the rendered PPI."
        case .noFrames:
            return "No rendered frames are available for video export."
        case .cannotCreatePixelBuffer:
            return "Could not create a video frame buffer."
        case .videoWriterFailed(let message):
            return message.isEmpty ? "Could not create MP4 video." : message
        }
    }
}

private struct PPIImageExporter {
    static func writePNG(
        frame: PPIFrame,
        opacity: Double,
        mapUnderlay: UIImage? = nil,
        mapOpacity: Double = 0.35,
        size: CGSize = CGSize(width: 1200, height: 1200)
    ) throws -> URL {
        let image = renderImage(frame: frame, opacity: opacity, mapUnderlay: mapUnderlay, mapOpacity: mapOpacity, size: size)
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

    static func writeMP4(
        frames: [PPIFrame],
        opacity: Double,
        mapUnderlay: UIImage? = nil,
        mapOpacity: Double = 0.35,
        size: CGSize = CGSize(width: 900, height: 900),
        framesPerSecond: Int32 = 8
    ) throws -> URL {
        guard let firstFrame = frames.first else {
            throw PPIImageExportError.noFrames
        }

        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(fileName(for: firstFrame) + "-sequence")
            .appendingPathExtension("mp4")
        try? FileManager.default.removeItem(at: fileURL)

        let writer = try AVAssetWriter(outputURL: fileURL, fileType: .mp4)
        let width = Int(size.width)
        let height = Int(size.height)
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
        ]
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = false
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
        ]
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: attributes)
        guard writer.canAdd(input) else {
            throw PPIImageExportError.videoWriterFailed("The MP4 writer could not add its video input.")
        }
        writer.add(input)
        writer.startWriting()
        writer.startSession(atSourceTime: .zero)

        let frameDuration = CMTime(value: 1, timescale: framesPerSecond)
        for (index, frame) in frames.enumerated() {
            while !input.isReadyForMoreMediaData {
                Thread.sleep(forTimeInterval: 0.01)
            }
            let image = renderImage(frame: frame, opacity: opacity, mapUnderlay: mapUnderlay, mapOpacity: mapOpacity, size: size)
            let buffer = try pixelBuffer(from: image, size: size)
            let presentationTime = CMTimeMultiply(frameDuration, multiplier: Int32(index))
            if !adaptor.append(buffer, withPresentationTime: presentationTime) {
                throw PPIImageExportError.videoWriterFailed(writer.error?.localizedDescription ?? "")
            }
        }

        input.markAsFinished()
        let semaphore = DispatchSemaphore(value: 0)
        writer.finishWriting {
            semaphore.signal()
        }
        semaphore.wait()

        guard writer.status == .completed else {
            throw PPIImageExportError.videoWriterFailed(writer.error?.localizedDescription ?? "")
        }
        return fileURL
    }

    private static func renderImage(
        frame: PPIFrame,
        opacity: Double,
        mapUnderlay: UIImage?,
        mapOpacity: Double,
        size: CGSize
    ) -> UIImage {
        let rendererFormat = UIGraphicsImageRendererFormat.default()
        rendererFormat.scale = 1
        let renderer = UIGraphicsImageRenderer(size: size, format: rendererFormat)
        return renderer.image { context in
            draw(frame: frame, opacity: opacity, mapUnderlay: mapUnderlay, mapOpacity: mapOpacity, in: context.cgContext, size: size)
        }
    }

    private static func draw(
        frame: PPIFrame,
        opacity: Double,
        mapUnderlay: UIImage?,
        mapOpacity: Double,
        in context: CGContext,
        size: CGSize
    ) {
        let rect = CGRect(origin: .zero, size: size)
        UIColor.systemBackground.setFill()
        context.fill(rect)

        let radius = min(size.width, size.height) * 0.46
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let rows = max(frame.rows, 1)
        let columns = max(frame.columns, 1)
        let angleStep = 360.0 / Double(rows)

        if let mapUnderlay {
            let mapRect = CGRect(origin: .zero, size: size)
            mapUnderlay.draw(in: mapRect, blendMode: .normal, alpha: mapOpacity)
        }

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

    private static func pixelBuffer(from image: UIImage, size: CGSize) throws -> CVPixelBuffer {
        let width = Int(size.width)
        let height = Int(size.height)
        var pixelBuffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32ARGB,
            [
                kCVPixelBufferCGImageCompatibilityKey as String: true,
                kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
            ] as CFDictionary,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let pixelBuffer else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        ) else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        UIGraphicsPushContext(context)
        image.draw(in: CGRect(origin: .zero, size: size))
        UIGraphicsPopContext()
        return pixelBuffer
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
        let elevation = elevationDeg.map { String(format: "%.1f°", $0) } ?? "elevation n/a"
        return "\(pulse) \(time) \(elevation)"
    }
}
