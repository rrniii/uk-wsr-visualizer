import AVFoundation
import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

private enum IPadWorkspaceMode: String, CaseIterable, Identifiable {
    case view = "View"
    case compare = "Compare"
    case projects = "Projects"

    var id: String { rawValue }
}

struct ContentView: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @StateObject private var model = VisualizerViewModel()
    @StateObject private var projectStore = WorkspaceProjectStore()
    @StateObject private var playback = PlaybackController()
    @State private var iPadColumnVisibility: NavigationSplitViewVisibility = .all
    @State private var iPadMode: IPadWorkspaceMode = .view

    var body: some View {
        ZStack {
            Group {
                if usesIPadWorkspace {
                    iPadWorkspace
                } else {
                    compactWorkspace
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

            if model.shouldShowLaunchLoadingScreen {
                LaunchLoadingView()
                    .transition(.opacity)
                    .zIndex(1)
                    .accessibilityIdentifier("LaunchLoadingView")
            }
        }
        .animation(.easeOut(duration: 0.25), value: model.shouldShowLaunchLoadingScreen)
    }

    private var usesIPadWorkspace: Bool {
        UIDevice.current.userInterfaceIdiom == .pad && horizontalSizeClass == .regular
    }

    private var compactWorkspace: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScanHeaderBar(model: model)
                RadarDisplayView(model: model, fixedHeight: 360)

                Divider()

                ScrollView {
                    controlsContent
                        .padding(12)
                }
                .background(Color(.systemGroupedBackground))
            }
            .navigationTitle("UK WSR")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { refreshToolbar }
        }
    }

    private var iPadWorkspace: some View {
        NavigationSplitView(columnVisibility: $iPadColumnVisibility) {
            ScrollView {
                VStack(spacing: 12) {
                    Picker("Workspace", selection: $iPadMode) {
                        ForEach(IPadWorkspaceMode.allCases) { mode in
                            Text(mode.rawValue).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier("IPadWorkspaceModePicker")

                    if iPadMode == .projects {
                        Text("Save, share, and restore portable desktop-compatible project files.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        controlsContent
                    }
                }
                .padding(14)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Data & Controls")
            .navigationBarTitleDisplayMode(.inline)
            .navigationSplitViewColumnWidth(min: 330, ideal: 370, max: 430)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("IPadControlsSidebar")
        } detail: {
            Group {
                switch iPadMode {
                case .view:
                    VStack(spacing: 0) {
                        ScanHeaderBar(model: model)
                        RadarDisplayView(model: model)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .layoutPriority(1)
                    }
                case .compare:
                    ComparisonWorkspaceView(primary: model)
                case .projects:
                    ProjectsWorkspaceView(model: model, store: projectStore)
                }
            }
            .background(Color(.secondarySystemBackground))
            .navigationTitle("UK WSR Visualizer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                refreshToolbar
                if iPadMode != .projects {
                    ToolbarItemGroup(placement: .navigationBarTrailing) {
                        Button {
                            model.stepTime(by: -1)
                        } label: {
                            Image(systemName: "backward.frame")
                        }
                        .disabled(!model.canStepTime)
                        .help("Previous scan")
                        .keyboardShortcut(.leftArrow, modifiers: [.option])

                        Button {
                            playback.toggle(model: model)
                        } label: {
                            Image(systemName: playback.isPlaying ? "pause.fill" : "play.fill")
                        }
                        .disabled(!model.canStepTime)
                        .help(playback.isPlaying ? "Pause playback" : "Play timeline")
                        .accessibilityIdentifier("TimelinePlaybackButton")
                        .keyboardShortcut(.space, modifiers: [])

                        Button {
                            model.stepTime(by: 1)
                        } label: {
                            Image(systemName: "forward.frame")
                        }
                        .disabled(!model.canStepTime)
                        .help("Next scan")
                        .keyboardShortcut(.rightArrow, modifiers: [.option])
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("IPadRadarWorkspace")
        }
        .navigationSplitViewStyle(.balanced)
        .onChange(of: iPadMode) { mode in
            if mode == .projects { playback.stop() }
        }
    }

    private var controlsContent: some View {
        LazyVStack(spacing: 12) {
            RadarControlsSection(model: model)
            MapSection(model: model)
            FilterSection(model: model)
            MetadataSection(model: model)
            ExportSection(model: model)
            RawCacheSection(model: model)
        }
    }

    @ToolbarContentBuilder
    private var refreshToolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .navigationBarTrailing) {
            Button {
                Task { await model.loadCatalog() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .disabled(model.isLoadingCatalog)
            .help("Reload catalog")
            .accessibilityLabel("Reload catalog")
        }
    }
}

private struct ComparisonWorkspaceView: View {
    @ObservedObject var primary: VisualizerViewModel
    @StateObject private var panelB = VisualizerViewModel()
    @StateObject private var panelC = VisualizerViewModel()
    @StateObject private var panelD = VisualizerViewModel()
    @State private var links = ComparisonLinks()
    @State private var isPreparing = false
    @State private var synchronizationTask: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 12) {
                Label("Four-panel comparison", systemImage: "square.grid.2x2")
                    .font(.headline)
                Spacer()
                Toggle("View", isOn: $links.view)
                Toggle("Time", isOn: $links.time)
                Toggle("Variable", isOn: $links.variable)
                Toggle("Elevation", isOn: $links.elevation)
                if isPreparing {
                    ProgressView().controlSize(.small)
                }
            }
            .toggleStyle(.button)
            .font(.caption)
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .accessibilityIdentifier("ComparisonLinkControls")

            GeometryReader { proxy in
                let panelHeight = max((proxy.size.height - 8) / 2, 220)
                Grid(horizontalSpacing: 8, verticalSpacing: 8) {
                    GridRow {
                        ComparisonPanel(title: "A", model: primary, height: panelHeight)
                        ComparisonPanel(title: "B", model: panelB, height: panelHeight)
                    }
                    GridRow {
                        ComparisonPanel(title: "C", model: panelC, height: panelHeight)
                        ComparisonPanel(title: "D", model: panelD, height: panelHeight)
                    }
                }
            }
            .padding([.horizontal, .bottom], 8)
        }
        .task(id: primary.selectedItemID) {
            await preparePanels()
        }
        .onChange(of: primary.selectedTime) { _ in synchronizeLinkedPanels() }
        .onChange(of: primary.selectedQuantity) { _ in synchronizeLinkedPanels() }
        .onChange(of: primary.selectedDataset) { _ in synchronizeLinkedPanels() }
        .onChange(of: links) { _ in synchronizeLinkedPanels() }
        .onDisappear { synchronizationTask?.cancel() }
        .accessibilityIdentifier("FourPanelComparisonWorkspace")
    }

    private var secondaryPanels: [VisualizerViewModel] { [panelB, panelC, panelD] }

    @MainActor
    private func preparePanels() async {
        guard primary.selectedItem != nil, !isPreparing else { return }
        isPreparing = true
        defer { isPreparing = false }
        for panel in secondaryPanels {
            if panel.catalog.isEmpty { await panel.loadCatalog() }
            await copySelection(to: panel, forceAllFields: true)
        }
    }

    private func synchronizeLinkedPanels() {
        synchronizationTask?.cancel()
        synchronizationTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard !Task.isCancelled else { return }
            guard !isPreparing else { return }
            for panel in secondaryPanels {
                guard !Task.isCancelled else { return }
                await copySelection(to: panel, forceAllFields: false)
            }
        }
    }

    @MainActor
    private func copySelection(to target: VisualizerViewModel, forceAllFields: Bool) async {
        guard primary.selectedItem != nil else { return }
        var state = ViewerProjectState(model: primary)
        if !links.time && !forceAllFields { state.time = target.selectedTime }
        if !links.variable && !forceAllFields { state.quantity = target.selectedQuantity }
        if !links.elevation && !forceAllFields { state.dataset = target.selectedDataset }
        if !links.view && !forceAllFields {
            state.opacity = target.filters.opacity
            state.basemap = target.mapSettings.style.rawValue
        } else {
            target.mapSettings = primary.mapSettings
        }
        await target.applyProjectState(state)
    }
}

private struct ComparisonPanel: View {
    var title: String
    @ObservedObject var model: VisualizerViewModel
    var height: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                    .frame(width: 24, height: 24)
                    .background(Color.accentColor, in: Circle())
                Text(model.selectedFieldSummary.isEmpty ? "No selection" : model.selectedFieldSummary)
                    .font(.caption.monospacedDigit())
                    .lineLimit(1)
                Spacer(minLength: 4)
                Menu("Variable") {
                    ForEach(model.availableQuantities, id: \.self) { quantity in
                        Button(quantity) { model.selectQuantity(quantity) }
                    }
                }
                .disabled(model.availableQuantities.isEmpty)
                Menu("Elevation") {
                    ForEach(model.availableDatasets) { record in
                        Button(datasetLabel(record)) { model.selectDataset(record.dataset) }
                    }
                }
                .disabled(model.availableDatasets.isEmpty)
            }
            .padding(.horizontal, 8)
            .frame(height: 34)
            .background(Color(.systemBackground))

            RadarDisplayView(model: model, fixedHeight: max(height - 34, 180))
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.25)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("ComparisonPanel\(title)")
    }

    private func datasetLabel(_ record: QuantityRecord) -> String {
        if let elevation = record.elevationDeg {
            return "\(record.dataset) · \(String(format: "%.2f°", elevation))"
        }
        if let height = record.nominalHeightM {
            return "\(record.dataset) · \(String(format: "%.0f m", height))"
        }
        return record.dataset
    }
}

private struct ProjectsWorkspaceView: View {
    @ObservedObject var model: VisualizerViewModel
    @ObservedObject var store: WorkspaceProjectStore
    @State private var title = "Radar project"
    @State private var isImporting = false
    @State private var manifestURL: URL?
    @State private var citationURL: URL?
    @State private var message = ""

    var body: some View {
        NavigationStack {
            List {
                Section("Current workspace") {
                    TextField("Project title", text: $title)
                    HStack {
                        Button {
                            saveCurrentProject()
                        } label: {
                            Label("Save project", systemImage: "folder.badge.plus")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.selectedItem == nil)

                        Button {
                            isImporting = true
                        } label: {
                            Label("Import", systemImage: "square.and.arrow.down")
                        }
                        .buttonStyle(.bordered)
                    }
                }

                Section("Saved projects") {
                    if store.projects.isEmpty {
                        Label("No saved projects", systemImage: "folder")
                            .font(.headline)
                        Text("Save the current radar workspace or import a desktop project file.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(store.projects) { project in
                        VStack(alignment: .leading, spacing: 7) {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(project.session.title).font(.headline)
                                    Text("\(project.session.state.radar) · \(project.session.state.start) · \(project.session.state.quantity)")
                                        .font(.caption.monospacedDigit())
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Load") {
                                    Task {
                                        await model.applyProjectState(project.session.state)
                                        message = "Loaded \(project.session.title)."
                                    }
                                }
                                .buttonStyle(.borderedProminent)
                                ShareLink(item: store.fileURL(for: project)) {
                                    Image(systemName: "square.and.arrow.up")
                                }
                                Button(role: .destructive) {
                                    try? store.delete(project)
                                } label: {
                                    Image(systemName: "trash")
                                }
                            }
                        }
                    }
                }

                Section("Provenance & citation") {
                    Button("Create artifact manifest") { createManifest() }
                        .disabled(model.selectedItem == nil)
                    if let manifestURL {
                        ShareLink(item: manifestURL) {
                            Label("Share manifest", systemImage: "doc.badge.arrow.up")
                        }
                    }
                    Button("Create citation record") { createCitation() }
                    if let citationURL {
                        ShareLink(item: citationURL) {
                            Label("Share citation", systemImage: "quote.bubble")
                        }
                    }
                    if let url = URL(string: model.selectedSourceURLString), !model.selectedSourceURLString.isEmpty {
                        ShareLink(item: url) {
                            Label("Share source-object URL", systemImage: "link")
                        }
                    }
                    Text(CitationPayload().userInstruction)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !message.isEmpty || !store.statusMessage.isEmpty {
                    Section("Status") {
                        Text(message.isEmpty ? store.statusMessage : message)
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("Projects & Provenance")
            .fileImporter(isPresented: $isImporting, allowedContentTypes: [.json]) { result in
                do {
                    let project = try store.importProject(from: result.get())
                    title = project.session.title
                    message = "Imported \(project.session.title)."
                } catch {
                    message = error.localizedDescription
                }
            }
        }
        .accessibilityIdentifier("ProjectsWorkspace")
    }

    private func saveCurrentProject() {
        do {
            _ = try store.save(.make(title: title, model: model))
            message = "Saved \(title)."
        } catch {
            message = error.localizedDescription
        }
    }

    private func createManifest() {
        do {
            manifestURL = try WorkspaceJSONExporter.writeManifest(
                ArtifactManifest.make(format: "screen_view", coordinateMode: "screen_view", model: model)
            )
            message = "Artifact manifest is ready to share."
        } catch {
            message = error.localizedDescription
        }
    }

    private func createCitation() {
        do {
            citationURL = try WorkspaceJSONExporter.writeCitation()
            message = "Citation record is ready to share."
        } catch {
            message = error.localizedDescription
        }
    }
}

private struct RadarDisplayView: View {
    @ObservedObject var model: VisualizerViewModel
    var fixedHeight: CGFloat?

    var body: some View {
        VStack(spacing: 0) {
            Group {
                if AppRuntime.isUITesting {
                    LightweightPPIPlotView(
                        frame: model.frame,
                        identifyResult: model.identifyResult,
                        pointerFields: model.pointerFields
                    )
                } else {
                    PPIPlotView(
                        frame: model.frame,
                        opacity: model.filters.opacity,
                        mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                        mapOpacity: model.mapSettings.opacity,
                        identifyResult: model.identifyResult,
                        showDetailedIdentifyReadout: model.showDetailedIdentifyReadout,
                        pointerFields: model.pointerFields,
                        onIdentify: { row, column in
                            model.identify(row: row, column: column)
                        }
                    )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: fixedHeight == nil ? .infinity : nil)
            .frame(height: fixedHeight)
            .background(Color(.secondarySystemBackground))
            .accessibilityIdentifier("PPIPlotView")

            if let frame = model.frame, let colorBar = ColorBarModel(frame: frame) {
                PlotColorBar(model: colorBar)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color(.systemBackground))
            }
        }
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

private enum AppUI {
    static let panelRadius: CGFloat = 8
    static let tileRadius: CGFloat = 8
    static let tileHeight: CGFloat = 60
    static let scanHeaderHeight: CGFloat = 56
    static let hairlineOpacity = 0.28
    static let sectionSpacing: CGFloat = 10
    static let controlSpacing: CGFloat = 8

    static var panelBackground: Color { Color(.secondarySystemGroupedBackground) }
    static var tileBackground: Color { Color(.tertiarySystemGroupedBackground) }
    static var insetBackground: Color { Color(.quaternarySystemFill) }
    static var hairline: Color { Color(.separator).opacity(hairlineOpacity) }

    static var valueFont: Font { .body.weight(.semibold) }
    static var labelFont: Font { .caption2.weight(.semibold) }
    static var metadataFont: Font { .caption.monospacedDigit() }
}

private struct PanelHeader<Trailing: View>: View {
    var title: String
    var systemImage: String
    var trailing: Trailing

    init(
        _ title: String,
        systemImage: String,
        @ViewBuilder trailing: () -> Trailing = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 8) {
            Label(title, systemImage: systemImage)
                .font(.headline)
            Spacer(minLength: 8)
            trailing
        }
    }
}

private struct MetadataPill: View {
    var text: String

    var body: some View {
        Text(text)
            .font(AppUI.metadataFont)
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(AppUI.insetBackground, in: Capsule())
    }
}

private struct ControlTile: View {
    var title: String
    var value: String
    var systemImage: String
    var showsChevron = true

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 28, height: 28)
                .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 2) {
                Text(title.uppercased())
                    .font(AppUI.labelFont)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(AppUI.valueFont)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.68)
            }

            Spacer(minLength: 4)

            if showsChevron {
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
    }
}

private struct ScanHeaderBar: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            statusIcon

            VStack(alignment: .leading, spacing: 2) {
                Text(primaryHeaderText)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(model.warningMessage == nil ? Color.primary : Color.orange)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .minimumScaleFactor(0.82)
                Text(secondaryHeaderText)
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .minimumScaleFactor(0.78)
            }
            .accessibilityIdentifier("StatusMessage")

            Spacer(minLength: 6)
        }
        .padding(.horizontal, 12)
        .frame(height: AppUI.scanHeaderHeight)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial)
        .accessibilityIdentifier("ScanHeaderBar")
    }

    private var isWorking: Bool {
        model.isLoadingCatalog || model.isDownloading || model.isRendering
    }

    private var scanMetadata: RadarGridMetadata? {
        guard
            !isWorking,
            model.warningMessage == nil,
            model.statusMessage.hasPrefix("Rendered "),
            let frame = model.frame
        else {
            return nil
        }
        return frame.metadata
    }

    @ViewBuilder
    private var statusIcon: some View {
        if isWorking {
            ProgressView()
                .controlSize(.small)
                .frame(width: 16)
        } else if scanMetadata != nil {
            Image(systemName: "checkmark.circle.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.green)
                .frame(width: 16)
        } else {
            Image(systemName: "circle")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(width: 16)
        }
    }

    private var primaryHeaderText: String {
        if model.warningMessage != nil {
            return model.statusMessage
        }
        if let metadata = scanMetadata {
            return metadata.statusPrimaryLine
        }
        return model.statusMessage
    }

    private var secondaryHeaderText: String {
        if let warning = model.warningMessage {
            return warning
        }
        if let metadata = scanMetadata {
            return metadata.statusSecondaryLine
        }
        return model.selectedFieldSummary.isEmpty ? "No field selected" : model.selectedFieldSummary
    }
}

private struct RadarControlsSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var isShowingCatalogSearch = false

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
                                model.selectTime(time)
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

private struct NoiseFloorControlsBlock: View {
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
        model.filters.noiseFloorEnabled ? NoiseCleanupPreset.nearest(to: model.filters.noiseFloorMarginDb) : .off
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
        let totalMasked = frame.noiseFloor.maskedCount + (frame.backgroundModel.applied ? frame.backgroundModel.maskedCount : 0)
        let percent = Double(totalMasked) / Double(before) * 100
        return String(format: "Cleanup: %.1f%% removed", percent)
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
        return rows
    }

}

private enum NoiseCleanupPreset: String, CaseIterable, Identifiable {
    case off
    case light
    case standard
    case strong

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off:
            return "Off"
        case .light:
            return "Light"
        case .standard:
            return "Standard"
        case .strong:
            return "Strong"
        }
    }

    var marginDb: Double {
        switch self {
        case .off:
            return 0
        case .light:
            return -3
        case .standard:
            return 0
        case .strong:
            return 3
        }
    }

    var detail: String {
        switch self {
        case .off:
            return "Shows all valid gates without background suppression."
        case .light:
            return "Only removes gates with very strong noise or clutter evidence."
        case .standard:
            return "Removes learned persistent background and velocity-supported static clutter."
        case .strong:
            return "Uses a wider near-noise evidence window for clutter-like speckle."
        }
    }

    var windowBins: Int {
        switch self {
        case .off:
            return 11
        case .light:
            return 9
        case .standard:
            return 11
        case .strong:
            return 13
        }
    }

    var staticClutterMinNeighbors: Int {
        switch self {
        case .off:
            return 3
        case .light:
            return 4
        case .standard:
            return 3
        case .strong:
            return 2
        }
    }

    func apply(to filters: inout RadarFilterSet) {
        filters.noiseFloorEnabled = self != .off
        filters.noiseFloorMethod = "estimated"
        filters.noiseFloorOperation = "mask"
        filters.noiseFloorMarginDb = marginDb
        filters.noiseFloorPercentile = 10
        filters.noiseFloorWindowBins = windowBins
        filters.staticClutterMinNeighbors = staticClutterMinNeighbors
        filters.textureCleanupEnabled = self != .off
        filters.companionQcEnabled = self != .off
        filters.backgroundModelEnabled = self != .off
        filters.backgroundDbzhExcessMaxDb = self == .off ? 8 : 12
        filters.backgroundEvidenceScoreThreshold = self == .off ? 2 : 1
    }

    static func nearest(to marginDb: Double) -> NoiseCleanupPreset {
        [NoiseCleanupPreset.light, .standard, .strong].min { left, right in
            abs(left.marginDb - marginDb) < abs(right.marginDb - marginDb)
        } ?? .standard
    }
}

private struct NoiseCleanupAdvancedSheet: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Background Cleaning") {
                    LabeledContent("Method", value: "Estimated profile")
                    HStack {
                        Text("Evidence margin dB")
                        Spacer()
                        Text(String(format: "%.1f dB", model.filters.noiseFloorMarginDb))
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                    Slider(value: $model.filters.noiseFloorMarginDb, in: -6...6, step: 0.5)
                        .onChange(of: model.filters.noiseFloorMarginDb) { _ in model.filtersChanged() }
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

private struct MapSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var isShowingAdvanced = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeader("Map", systemImage: "map") {
                if model.isLoadingMapSnapshot {
                    ProgressView()
                        .controlSize(.small)
                }
            }

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

                Spacer(minLength: 0)

                Button {
                    isShowingAdvanced = true
                } label: {
                    Label("Advanced", systemImage: "slider.horizontal.3")
                }
                .buttonStyle(.bordered)
                .disabled(!model.mapSettings.isEnabled)
            }

            HStack {
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
        .sheet(isPresented: $isShowingAdvanced) {
            MapAdvancedSheet(model: model)
                .presentationDetents([.medium])
        }
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
}

private struct MapAdvancedSheet: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Map") {
                    HStack {
                        Text("Map opacity")
                        Spacer()
                        Text("\(Int(model.mapSettings.opacity * 100))%")
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                    Slider(value: mapOpacityBinding, in: 0.15...0.85)
                        .disabled(!model.mapSettings.isEnabled)
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
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Data source", systemImage: "externaldrive.connected.to.line.below")

                        Picker("Radar era", selection: dataEraBinding) {
                            ForEach(RadarDataEra.allCases) { era in
                                Text(era.displayName).tag(era)
                            }
                        }
                        .pickerStyle(.menu)
                        .accessibilityIdentifier("CatalogEraPicker")

                        Text(model.dataEra.selectionExplanation)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Search", systemImage: "magnifyingglass") {
                            MetadataPill(text: model.catalogSearchSummary)
                        }
                        CatalogSearchField(text: criteriaBinding(\.text))
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Filters", systemImage: "line.3.horizontal.decrease.circle")

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogFilterMenu(
                                title: "Radar",
                                value: catalogRadarFilterText,
                                selection: criteriaBinding(\.radar)
                            ) {
                                Text("Any radar").tag("")
                                ForEach(model.catalogRadarOptions, id: \.self) { radar in
                                    Text(model.radarDisplayName(radar)).tag(radar)
                                }
                            }

                            CatalogFilterMenu(
                                title: "Year",
                                value: catalogYearFilterText,
                                selection: criteriaBinding(\.year)
                            ) {
                                Text("Any year").tag("")
                                ForEach(model.catalogYearOptions, id: \.self) { year in
                                    Text(year).tag(year)
                                }
                            }
                        }

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogDateField(title: "Start", text: criteriaBinding(\.startDate))
                            CatalogDateField(title: "End", text: criteriaBinding(\.endDate))
                        }

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogFilterMenu(
                                title: "Pulse",
                                value: catalogPulseFilterText,
                                selection: criteriaBinding(\.pulse)
                            ) {
                                Text("Any pulse").tag("")
                                ForEach(model.catalogPulseOptions, id: \.self) { pulse in
                                    Text(pulse).tag(pulse)
                                }
                            }

                            CatalogFilterMenu(
                                title: "Variable",
                                value: catalogQuantityFilterText,
                                selection: criteriaBinding(\.quantity)
                            ) {
                                Text("Any variable").tag("")
                                ForEach(model.catalogQuantityOptions, id: \.self) { quantity in
                                    Text(quantity).tag(quantity)
                                }
                            }
                        }

                        HStack(spacing: 8) {
                            Button {
                                model.setCatalogSearchToFirstDay()
                            } label: {
                                Label("Oldest", systemImage: "backward.end")
                            }
                            .disabled(model.catalogDateRange == nil)

                            Button {
                                model.setCatalogSearchToLatestDay()
                            } label: {
                                Label("Newest", systemImage: "forward.end")
                            }
                            .disabled(model.catalogDateRange == nil)

                            Button {
                                model.clearCatalogDateFilters()
                            } label: {
                                Label("Clear dates", systemImage: "xmark.circle")
                            }
                        }
                        .font(.caption)
                        .buttonStyle(.bordered)

                        Text(model.catalogCoverageStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Shortcuts", systemImage: "bolt")

                        CatalogActionButton(
                            title: "Closest radar, latest day",
                            subtitle: "Use this phone's location to pick the nearest radar.",
                            systemImage: "location.fill"
                        ) {
                            Task {
                                if await model.selectNearestRadarLatest() {
                                    dismiss()
                                }
                            }
                        }

                        CatalogActionButton(
                            title: "Latest available day",
                            subtitle: "Open the newest published catalog item.",
                            systemImage: "clock.arrow.circlepath"
                        ) {
                            if model.selectLatestPublishedDay() {
                                dismiss()
                            }
                        }

                        CatalogActionButton(
                            title: "Selected radar only",
                            subtitle: "Show days for the radar currently on screen.",
                            systemImage: "scope",
                            isEnabled: model.selectedItem != nil
                        ) {
                            model.setCatalogSearchToCurrentRadar()
                        }
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 8) {
                        PanelHeader("Results", systemImage: "list.bullet") {
                            if model.isLoadingCoverage {
                                ProgressView()
                                    .controlSize(.small)
                            }
                        }

                        if model.filteredCatalogItems.isEmpty {
                            Text("No matching catalog items")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
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
                    }
                    .panelStyle()

                    if !model.recentSelections.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            PanelHeader("Recent", systemImage: "clock")

                            ForEach(Array(model.recentSelections.prefix(5))) { recent in
                                Button {
                                    if model.applyRecentSelection(recent) {
                                        dismiss()
                                    }
                                } label: {
                                    CatalogRecentRow(recent: recent)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .panelStyle()
                    }
                }
                .padding(12)
            }
            .background(Color(.systemGroupedBackground))
            .accessibilityIdentifier("CatalogSearchList")
            .navigationTitle("Select Data")
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

    private var catalogRadarFilterText: String {
        model.catalogSearch.radar.isEmpty ? "Any" : model.radarDisplayName(model.catalogSearch.radar)
    }

    private var dataEraBinding: Binding<RadarDataEra> {
        Binding(
            get: { model.dataEra },
            set: { model.selectDataEra($0) }
        )
    }

    private var catalogYearFilterText: String {
        model.catalogSearch.year.isEmpty ? "Any" : model.catalogSearch.year
    }

    private var catalogPulseFilterText: String {
        model.catalogSearch.pulse.isEmpty ? "Any" : model.catalogSearch.pulse
    }

    private var catalogQuantityFilterText: String {
        model.catalogSearch.quantity.isEmpty ? "Any" : model.catalogSearch.quantity
    }

    private func criteriaBinding<Value>(_ keyPath: WritableKeyPath<CatalogSearchCriteria, Value>) -> Binding<Value> {
        Binding(
            get: { model.catalogSearch[keyPath: keyPath] },
            set: { model.catalogSearch[keyPath: keyPath] = $0 }
        )
    }
}

private struct CatalogSearchField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
            TextField("Search catalog", text: $text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .accessibilityIdentifier("CatalogSearchTextField")
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear catalog search")
            }
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
    }
}

private struct CatalogFilterMenu<Content: View>: View {
    var title: String
    var value: String
    @Binding var selection: String
    var content: () -> Content

    init(
        title: String,
        value: String,
        selection: Binding<String>,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.value = value
        self._selection = selection
        self.content = content
    }

    var body: some View {
        Menu {
            Picker(title, selection: $selection) {
                content()
            }
        } label: {
            ControlTile(title: title, value: value, systemImage: "line.3.horizontal.decrease.circle", showsChevron: true)
        }
        .buttonStyle(.plain)
    }
}

private struct CatalogActionButton: View {
    var title: String
    var subtitle: String
    var systemImage: String
    var isEnabled = true
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: systemImage)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.blue)
                    .frame(width: 30, height: 30)
                    .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(AppUI.valueFont)
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight, alignment: .leading)
            .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
            .overlay(
                RoundedRectangle(cornerRadius: AppUI.tileRadius)
                    .stroke(AppUI.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.5)
    }
}

private struct CatalogRecentRow: View {
    var recent: RecentCatalogSelection

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 28, height: 28)
                .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 2) {
                Text(recent.title)
                    .font(AppUI.valueFont)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(recent.detailText.isEmpty ? "Auto field selection" : recent.detailText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
        }
        .padding(.vertical, 6)
    }
}

private struct CatalogDateField: View {
    var title: String
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("YYYY-MM-DD", text: $text)
                .keyboardType(.numbersAndPunctuation)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(AppUI.valueFont)
                .accessibilityIdentifier("Catalog\(title.replacingOccurrences(of: " ", with: ""))Field")
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight, alignment: .leading)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
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

            if model.showDetailedIdentifyReadout {
                DisclosureGroup("Tap readout fields") {
                    Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                        GridRow {
                            Toggle("Value", isOn: $model.pointerFields.value)
                            Toggle("Raw", isOn: $model.pointerFields.rawValue)
                        }
                        GridRow {
                            Toggle("Range", isOn: $model.pointerFields.range)
                            Toggle("Azimuth", isOn: $model.pointerFields.azimuth)
                        }
                        GridRow {
                            Toggle("Height", isOn: $model.pointerFields.beamHeight)
                            Toggle("Elevation", isOn: $model.pointerFields.elevation)
                        }
                        GridRow {
                            Toggle("Coordinates", isOn: $model.pointerFields.coordinates)
                            Toggle("Gate indices", isOn: $model.pointerFields.gateIndices)
                        }
                    }
                    .font(.caption)
                    .toggleStyle(.switch)
                    .padding(.top, 4)
                }
                .font(.caption)
                .accessibilityIdentifier("PointerFieldControls")
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
                    OptionalDoubleField(title: "CAPPI m", value: $model.filters.cappiHeightM, onCommit: { model.fieldSelectionChanged() })
                    Color.clear.frame(height: 0)
                }
            }

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

private struct MetadataSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var didCopySourceURL = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader("Metadata", systemImage: "doc.text.magnifyingglass")

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

private struct VideoExportResumeStatus: Equatable {
    var completed: Int
    var requested: Int

    var remaining: Int {
        max(0, requested - completed)
    }

    var fractionText: String {
        "\(completed) / \(requested)"
    }
}

private struct ExportQueueStatusCard: View {
    var title: String
    var detail: String
    var resumeStatus: VideoExportResumeStatus?
    var message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                    .font(.caption.weight(.semibold))
                Spacer(minLength: 8)
                if let resumeStatus {
                    Text(resumeStatus.fractionText)
                        .font(.caption2.monospacedDigit().weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }

            Text(detail)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .lineLimit(2)

            if let resumeStatus, resumeStatus.requested > 0 {
                ProgressView(value: Double(resumeStatus.completed), total: Double(resumeStatus.requested))
                    .accessibilityIdentifier("VideoExportQueueProgress")
            }

            Text(message)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(10)
        .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
        .accessibilityIdentifier("VideoExportQueueStatusCard")
    }
}

private struct ExportSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var exportedPNGURL: URL?
    @State private var exportedVideoURL: URL?
    @State private var exportManifestURL: URL?
    @State private var companionArtifacts: [ExportedArtifact] = []
    @State private var exportMessage: String?
    @State private var resumeStatus: VideoExportResumeStatus?
    @State private var videoExportHadFailure = false
    @State private var videoExportMode: VideoExportMode = .fast

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader("Export", systemImage: "square.and.arrow.up") {
                if model.isExportingVideo {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            HStack(spacing: 8) {
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
                    Label(videoButtonTitle, systemImage: "film")
                }
                .buttonStyle(.bordered)
                .disabled(model.frame == nil || model.availableTimes.count < 2 || model.isExportingVideo)

                if resumeStatus != nil {
                    Button(role: .destructive) {
                        clearResumeFrames()
                    } label: {
                        Label("Clear saved", systemImage: "trash")
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .disabled(model.isExportingVideo)
                }

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

            if let exportManifestURL {
                ShareLink(item: exportManifestURL) {
                    Label("Share Manifest", systemImage: "doc.badge.arrow.up")
                }
                .buttonStyle(.bordered)
            }

            if !companionArtifacts.isEmpty {
                HStack(spacing: 8) {
                    ForEach(companionArtifacts) { artifact in
                        ShareLink(item: artifact.url) {
                            Label(artifact.label, systemImage: "square.and.arrow.up")
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .font(.caption)
            }

            Picker("MP4 mode", selection: $videoExportMode) {
                ForEach(VideoExportMode.allCases) { mode in
                    Text(mode.displayName).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .disabled(model.isExportingVideo)
            .accessibilityIdentifier("VideoExportModePicker")

            if model.isExportingVideo {
                ExportQueueStatusCard(
                    title: "Export running",
                    detail: model.videoExportProgress,
                    resumeStatus: resumeStatus,
                    message: runningExportMessage
                )
            } else if let resumeStatus {
                ExportQueueStatusCard(
                    title: "Resume available",
                    detail: "\(resumeStatus.fractionText) frames saved, \(resumeStatus.remaining) remaining.",
                    resumeStatus: resumeStatus,
                    message: "Tap Resume MP4 to continue from the saved frames."
                )
            }

            if model.isExportingVideo {
                VStack(alignment: .leading, spacing: 4) {
                    ProgressView(model.videoExportProgress)
                    Text("Keeping this device awake while exporting.")
                        .foregroundStyle(.secondary)
                }
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
            exportManifestURL = nil
            companionArtifacts = []
            exportMessage = nil
            videoExportHadFailure = false
        }
        .task(id: resumeLookupKey) {
            await refreshResumeStatus()
        }
    }

    private func createPNG() {
        guard let frame = model.frame else {
            exportMessage = "No rendered PPI"
            return
        }
        do {
            let pngURL = try PPIImageExporter.writePNG(
                frame: frame,
                opacity: model.filters.opacity,
                mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                mapOpacity: model.mapSettings.opacity
            )
            exportedPNGURL = pngURL
            companionArtifacts = try GeospatialExporter.writeCompanions(pngURL: pngURL, frame: frame)
            createManifest(format: "screenshot_png")
            exportMessage = "PNG, metadata, KMZ, and screen-view GeoTIFF ready"
        } catch {
            exportedPNGURL = nil
            companionArtifacts = []
            exportMessage = error.localizedDescription
        }
    }

    private func createManifest(format: String) {
        do {
            exportManifestURL = try WorkspaceJSONExporter.writeManifest(
                ArtifactManifest.make(format: format, coordinateMode: "screen_view", model: model)
            )
        } catch {
            exportManifestURL = nil
        }
    }

    private var videoButtonTitle: String {
        if resumeStatus != nil {
            return "Resume MP4"
        }
        if videoExportHadFailure {
            return "Retry MP4"
        }
        switch videoExportMode {
        case .fast:
            return "Create MP4"
        case .preview:
            return "Preview MP4"
        case .resumeSafe:
            return "Safe MP4"
        }
    }

    private var runningExportMessage: String {
        switch activeExportMode {
        case .fast:
            return "Streaming directly into MP4. Keep UK WSR open for best speed."
        case .preview:
            return "Creating a smaller preview MP4 for a quick check."
        case .resumeSafe:
            return "Frames are saved as they render. If iOS stops the export, reopen UK WSR and resume."
        }
    }

    private var activeExportMode: VideoExportMode {
        resumeStatus == nil ? videoExportMode : .resumeSafe
    }

    private var resumeLookupKey: String {
        videoExportSignature() + "|times=" + model.availableTimes.joined(separator: ",")
    }

    @MainActor
    private func refreshResumeStatus() async {
        let signature = videoExportSignature()
        let times = model.availableTimes
        guard times.count > 1 else {
            resumeStatus = nil
            return
        }
        let status = await Task.detached(priority: .utility) {
            VideoExportFrameStore.resumeStatus(signature: signature, requestedTimes: times)
        }.value
        guard signature == videoExportSignature(), times == model.availableTimes else {
            return
        }
        if let status {
            resumeStatus = VideoExportResumeStatus(completed: status.completed, requested: status.requested)
        } else {
            resumeStatus = nil
        }
    }

    private func clearResumeFrames() {
        VideoExportFrameStore.clear(signature: videoExportSignature())
        resumeStatus = nil
        videoExportHadFailure = false
        exportMessage = "Cleared saved MP4 frames."
    }

    private func videoExportDisplayName() -> String {
        let itemTitle = model.selectedItem?.title ?? "UK WSR"
        return [
            itemTitle,
            model.selectedPulse,
            model.selectedQuantity,
            model.selectedElevationText,
        ]
        .filter { !$0.isEmpty }
        .joined(separator: " ")
    }

    private func videoExportOutputBaseName(mode: VideoExportMode) -> String {
        let suffix = mode == .preview ? "-preview" : "-sequence"
        return VideoExportFrameStore.safeFileComponent(videoExportDisplayName()) + suffix
    }

    private func videoExportSignature() -> String {
        let filters = model.filters
        let mapSettings = model.mapSettings
        return [
            model.selectedItem?.id ?? "no-item",
            model.selectedPulse,
            model.selectedQuantity,
            model.selectedDataset,
            optional(filters.minRangeKm),
            optional(filters.maxRangeKm),
            optional(filters.minAzimuthDeg),
            optional(filters.maxAzimuthDeg),
            optional(filters.minValue),
            optional(filters.maxValue),
            optional(filters.cappiHeightM),
            filters.displayRangeMode.rawValue,
            optional(filters.displayMin),
            optional(filters.displayMax),
            filters.palette,
            formatted(filters.opacity),
            String(filters.noiseFloorEnabled),
            filters.noiseFloorMethod,
            formatted(filters.noiseFloorMarginDb),
            filters.noiseFloorOperation,
            formatted(filters.noiseFloorPercentile),
            String(filters.noiseFloorWindowBins),
            String(filters.textureCleanupEnabled),
            String(filters.companionQcEnabled),
            formatted(filters.staticClutterDbzMin),
            formatted(filters.staticClutterVradAbsMax),
            String(filters.staticClutterMinNeighbors),
            String(filters.backgroundModelEnabled),
            formatted(filters.backgroundPersistentFrequencyMin),
            String(filters.backgroundMinSamples),
            formatted(filters.backgroundStaticVradFrequencyMin),
            formatted(filters.backgroundLowSqiFrequencyMin),
            formatted(filters.backgroundDbzhExcessMaxDb),
            String(filters.backgroundEvidenceScoreThreshold),
            String(mapSettings.isEnabled),
            mapSettings.style.rawValue,
            formatted(mapSettings.opacity),
        ].joined(separator: "|")
    }

    private func optional(_ value: Double?) -> String {
        value.map { formatted($0) } ?? "nil"
    }

    private func formatted(_ value: Double) -> String {
        String(format: "%.5f", value)
    }

    private func createVideo() {
        exportedVideoURL = nil
        exportMessage = nil
        videoExportHadFailure = false
        let requestedMode = activeExportMode
        let backgroundSession = BackgroundExportSession(name: "UK WSR MP4 Export") {
            model.cancelVideoExportForBackgroundExpiration()
        }
        Task {
            var sequenceWriter: PPIImageExporter.MP4SequenceWriter?
            var frameStore: VideoExportFrameStore?
            defer {
                model.isExportingVideo = false
                backgroundSession.end()
                Task { await refreshResumeStatus() }
            }
            do {
                if model.mapSettings.isEnabled && model.mapSnapshotImage == nil {
                    await model.refreshMapSnapshot()
                }
                guard !backgroundSession.isExpired else {
                    throw VideoExportError.backgroundTimeExpired
                }
                let plan = try await model.makeVideoExportPlan(mode: requestedMode)
                let exportTimes = plan.requestedTimes
                if plan.mode == .fast || plan.mode == .preview {
                    let writer = try PPIImageExporter.MP4SequenceWriter(
                        baseName: videoExportOutputBaseName(mode: plan.mode),
                        size: plan.quality.size,
                        framesPerSecond: plan.quality.framesPerSecond
                    )
                    sequenceWriter = writer
                    let summary = try await model.renderVideoFrames(
                        for: plan,
                        shouldStop: { backgroundSession.isExpired },
                        onFrame: { frame, _, _ in
                            if backgroundSession.isExpired {
                                throw VideoExportError.backgroundTimeExpired
                            }
                            return try writer.appendDirect(
                                frame: frame,
                                opacity: model.filters.opacity,
                                mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                                mapOpacity: model.mapSettings.opacity,
                                isCancelled: { backgroundSession.isExpired }
                            )
                        }
                    )
                    guard writer.frameCount > 0 else {
                        throw VideoExportError.noFrames
                    }
                    exportedVideoURL = try writer.finish()
                    createManifest(format: "mp4")
                    sequenceWriter = nil
                    let skipped = summary.skippedFrames > 0 ? " Skipped \(summary.skippedFrames)." : ""
                    exportMessage = "\(plan.mode.statusName) MP4 saved to Files > On My Device > UK WSR > Downloads.\(skipped) \(summary.metrics.summaryText)"
                    videoExportHadFailure = false
                    return
                }

                let store = try VideoExportFrameStore(
                    signature: videoExportSignature(),
                    displayName: videoExportDisplayName(),
                    outputBaseName: videoExportOutputBaseName(mode: .resumeSafe),
                    requestedTimes: exportTimes
                )
                frameStore = store
                let savedTimes = store.completedTimes
                if !savedTimes.isEmpty {
                    exportMessage = "Resuming MP4 export from \(savedTimes.count) saved frame\(savedTimes.count == 1 ? "" : "s")."
                }
                let summary = try await model.renderVideoFrames(
                    for: plan,
                    skipTimes: savedTimes,
                    shouldStop: { backgroundSession.isExpired },
                    onFrame: { frame, index, _ in
                        if backgroundSession.isExpired {
                            throw VideoExportError.backgroundTimeExpired
                        }
                        let image = PPIImageExporter.renderVideoFrameImage(
                            frame: frame,
                            opacity: model.filters.opacity,
                            mapUnderlay: model.mapSettings.isEnabled ? model.mapSnapshotImage : nil,
                            mapOpacity: model.mapSettings.opacity
                        )
                        try store.saveFrame(image: image, index: index - 1, time: frame.metadata.time)
                        return nil
                    }
                )

                let entries = store.availableFrameEntries()
                guard !entries.isEmpty else {
                    throw VideoExportError.noFrames
                }
                guard !backgroundSession.isExpired else {
                    exportMessage = "Saved \(entries.count) frame\(entries.count == 1 ? "" : "s") for resume. Reopen UK WSR and tap Resume MP4 to continue."
                    return
                }

                model.isExportingVideo = true
                sequenceWriter = try PPIImageExporter.MP4SequenceWriter(
                    baseName: store.outputBaseName,
                    size: plan.quality.size,
                    framesPerSecond: plan.quality.framesPerSecond
                )
                var encodedFrames = 0
                for entry in entries {
                    if backgroundSession.isExpired {
                        break
                    }
                    guard let image = UIImage(contentsOfFile: entry.url.path) else {
                        continue
                    }
                    try sequenceWriter?.append(image: image, isCancelled: { backgroundSession.isExpired })
                    encodedFrames += 1
                    model.videoExportProgress = "Encoding \(encodedFrames) / \(entries.count)"
                    await Task.yield()
                }
                guard let sequenceWriter, sequenceWriter.frameCount > 0 else {
                    throw VideoExportError.noFrames
                }
                exportedVideoURL = try sequenceWriter.finish()
                createManifest(format: "mp4")
                let didComplete = !summary.stoppedEarly &&
                    !backgroundSession.isExpired &&
                    encodedFrames == exportTimes.count &&
                    store.completedTimes.count == exportTimes.count
                if didComplete {
                    store.clear()
                    exportMessage = "Resume-safe MP4 saved to Files > On My Device > UK WSR > Downloads. \(summary.metrics.summaryText)"
                    videoExportHadFailure = false
                } else {
                    exportMessage = "Partial MP4 saved to Files > On My Device > UK WSR > Downloads (\(encodedFrames) of \(exportTimes.count) frames). Tap Resume MP4 later to finish the full video. \(summary.metrics.summaryText)"
                    videoExportHadFailure = false
                }
            } catch {
                sequenceWriter?.cancel()
                exportedVideoURL = nil
                videoExportHadFailure = true
                if backgroundSession.isExpired, let frameStore {
                    let entries = frameStore.availableFrameEntries()
                    exportMessage = entries.isEmpty ?
                        VideoExportError.backgroundTimeExpired.localizedDescription :
                        "Saved \(entries.count) frame\(entries.count == 1 ? "" : "s") for resume. Reopen UK WSR and tap Resume MP4 to continue."
                } else {
                    exportMessage = error.localizedDescription
                }
            }
        }
    }
}

private final class BackgroundExportSession {
    private let lock = NSLock()
    private var backgroundTaskID: UIBackgroundTaskIdentifier = .invalid
    private var didExpire = false
    private var didEnd = false
    private let previousIdleTimerDisabled: Bool
    private let onExpiration: () -> Void

    init(name: String, onExpiration: @escaping () -> Void) {
        self.onExpiration = onExpiration
        previousIdleTimerDisabled = UIApplication.shared.isIdleTimerDisabled
        UIApplication.shared.isIdleTimerDisabled = true
        backgroundTaskID = UIApplication.shared.beginBackgroundTask(withName: name) { [weak self] in
            guard let self else { return }
            self.markExpired()
            DispatchQueue.main.async {
                self.onExpiration()
                self.end()
            }
        }
    }

    var isExpired: Bool {
        lock.lock()
        defer { lock.unlock() }
        return didExpire
    }

    func end() {
        lock.lock()
        if didEnd {
            lock.unlock()
            return
        }
        didEnd = true
        let taskID = backgroundTaskID
        backgroundTaskID = .invalid
        lock.unlock()

        DispatchQueue.main.async {
            UIApplication.shared.isIdleTimerDisabled = self.previousIdleTimerDisabled
            if taskID != .invalid {
                UIApplication.shared.endBackgroundTask(taskID)
            }
        }
    }

    private func markExpired() {
        lock.lock()
        didExpire = true
        lock.unlock()
    }
}

private struct VideoExportJobManifest: Codable {
    var id: String
    var signature: String
    var displayName: String
    var outputBaseName: String
    var requestedTimes: [String]
    var completedTimes: [String]
    var createdAt: Date
    var updatedAt: Date
}

struct VideoExportFrameEntry {
    var index: Int
    var time: String
    var url: URL
}

final class VideoExportFrameStore {
    private let directory: URL
    private let framesDirectory: URL
    private let manifestURL: URL
    private var manifest: VideoExportJobManifest

    var outputBaseName: String { manifest.outputBaseName }
    var requestedFrameCount: Int { manifest.requestedTimes.count }

    var completedTimes: Set<String> {
        let completed = Set(manifest.completedTimes)
        return Set(manifest.requestedTimes.enumerated().compactMap { index, time in
            guard completed.contains(time), FileManager.default.fileExists(atPath: frameURL(index: index, time: time).path) else {
                return nil
            }
            return time
        })
    }

    init(signature: String, displayName: String, outputBaseName: String, requestedTimes: [String]) throws {
        let id = Self.stableIdentifier(for: signature)
        let root = try PPIImageExporter.videoExportJobsDirectory()
        directory = root.appendingPathComponent(id, isDirectory: true)
        framesDirectory = directory.appendingPathComponent("frames", isDirectory: true)
        manifestURL = directory.appendingPathComponent("manifest.json")

        if let existing = Self.loadManifest(from: manifestURL),
           existing.signature == signature,
           existing.requestedTimes == requestedTimes {
            manifest = existing
            manifest.displayName = displayName
            manifest.outputBaseName = outputBaseName
        } else {
            try? FileManager.default.removeItem(at: directory)
            let now = Date()
            manifest = VideoExportJobManifest(
                id: id,
                signature: signature,
                displayName: displayName,
                outputBaseName: outputBaseName,
                requestedTimes: requestedTimes,
                completedTimes: [],
                createdAt: now,
                updatedAt: now
            )
        }

        try FileManager.default.createDirectory(at: framesDirectory, withIntermediateDirectories: true, attributes: nil)
        try saveManifest()
    }

    static func resumeStatus(signature: String, requestedTimes: [String]) -> (completed: Int, requested: Int)? {
        let id = stableIdentifier(for: signature)
        guard let root = try? PPIImageExporter.videoExportJobsDirectory() else { return nil }
        let directory = root.appendingPathComponent(id, isDirectory: true)
        let manifestURL = directory.appendingPathComponent("manifest.json")
        guard let manifest = loadManifest(from: manifestURL),
              manifest.signature == signature,
              manifest.requestedTimes == requestedTimes else {
            return nil
        }
        let framesDirectory = directory.appendingPathComponent("frames", isDirectory: true)
        let completed = Set(manifest.completedTimes)
        let frameCount = manifest.requestedTimes.enumerated().filter { index, time in
            completed.contains(time) &&
                FileManager.default.fileExists(atPath: frameURL(framesDirectory: framesDirectory, index: index, time: time).path)
        }.count
        guard frameCount > 0 else { return nil }
        return (frameCount, manifest.requestedTimes.count)
    }

    static func clear(signature: String) {
        let id = stableIdentifier(for: signature)
        guard let root = try? PPIImageExporter.videoExportJobsDirectory() else { return }
        let directory = root.appendingPathComponent(id, isDirectory: true)
        try? FileManager.default.removeItem(at: directory)
    }

    func saveFrame(image: UIImage, index: Int, time: String) throws {
        let destination = frameURL(index: index, time: time)
        guard let data = image.jpegData(compressionQuality: 0.92) ?? image.pngData() else {
            throw PPIImageExportError.noPNGData
        }
        try data.write(to: destination, options: .atomic)
        if !manifest.completedTimes.contains(time) {
            manifest.completedTimes.append(time)
        }
        manifest.updatedAt = Date()
        try saveManifest()
    }

    func availableFrameEntries() -> [VideoExportFrameEntry] {
        let completed = completedTimes
        return manifest.requestedTimes.enumerated().compactMap { index, time in
            guard completed.contains(time) else { return nil }
            let url = frameURL(index: index, time: time)
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
            return VideoExportFrameEntry(index: index, time: time, url: url)
        }
    }

    func clear() {
        try? FileManager.default.removeItem(at: directory)
    }

    private func frameURL(index: Int, time: String) -> URL {
        Self.frameURL(framesDirectory: framesDirectory, index: index, time: time)
    }

    private static func frameURL(framesDirectory: URL, index: Int, time: String) -> URL {
        framesDirectory
            .appendingPathComponent(String(format: "%05d-", index + 1) + safeFileComponent(time))
            .appendingPathExtension("jpg")
    }

    private func saveManifest() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        try data.write(to: manifestURL, options: .atomic)
    }

    private static func loadManifest(from url: URL) -> VideoExportJobManifest? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(VideoExportJobManifest.self, from: data)
    }

    static func safeFileComponent(_ raw: String) -> String {
        let value = raw
            .lowercased()
            .map { character -> Character in
                character.isLetter || character.isNumber || character == "-" ? character : "-"
            }
            .reduce(into: "") { output, character in
                output.append(character)
            }
        let collapsed = value.replacingOccurrences(of: "-+", with: "-", options: .regularExpression)
        return collapsed.trimmingCharacters(in: CharacterSet(charactersIn: "-")).isEmpty ?
            "uk-wsr-export" :
            String(collapsed.trimmingCharacters(in: CharacterSet(charactersIn: "-")).prefix(80))
    }

    private static func stableIdentifier(for value: String) -> String {
        var hash: UInt64 = 1469598103934665603
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 1099511628211
        }
        return String(hash, radix: 16)
    }
}

private struct RawCacheSection: View {
    @ObservedObject var model: VisualizerViewModel
    @State private var sourceShareURL: URL?
    @State private var sourceShareMessage = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader("Raw Cache", systemImage: "externaldrive") {
                MetadataPill(text: model.cacheStatus.displayText)
            }

            HStack {
                Button {
                    prepareSource()
                } label: {
                    Label("Prepare Source", systemImage: "arrow.down.doc")
                }
                .buttonStyle(.bordered)
                .disabled(model.selectedItem == nil || model.isDownloading || model.isRendering)

                if let sourceShareURL {
                    ShareLink(item: sourceShareURL) {
                        Label("Share HDF5", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }

                Spacer(minLength: 0)
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
                    if frame.backgroundModel.applied {
                        Text("\(frame.backgroundModel.maskedCount) background")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Toggle(isOn: $model.showDataID) {
                Text("Show Data ID")
                    .font(.caption)
            }

            if !sourceShareMessage.isEmpty {
                Text(sourceShareMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .panelStyle()
        .onChange(of: model.selectedItemID) { _ in
            sourceShareURL = nil
            sourceShareMessage = ""
        }
    }

    private func prepareSource() {
        Task {
            do {
                sourceShareURL = try await model.prepareSelectedSourceForSharing()
                sourceShareMessage = "Native HDF5 source is ready to share."
            } catch {
                sourceShareMessage = error.localizedDescription
            }
        }
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
    var showDetailedIdentifyReadout: Bool
    var pointerFields: PointerFieldPreferences
    var onIdentify: (Int, Int) -> Void

    @State private var viewportScale: CGFloat = 1
    @State private var viewportOffset: CGSize = .zero
    @State private var suppressIdentifyAfterPinch = false
    @State private var lastViewportResetKey: String?
    @GestureState private var gestureScale: CGFloat = 1
    @GestureState private var gestureOffset: CGSize = .zero
    private let maximumRadarZoomScale: CGFloat = 80

    var body: some View {
        GeometryReader { proxy in
            let viewport = activeViewport(size: proxy.size)

            ZStack(alignment: .bottomLeading) {
                ZStack {
                    Canvas { context, size in
                        drawBackground(context: context, size: size)
                        var dataContext = context
                        applyDataViewport(viewport, to: &dataContext, size: size)
                        if let mapUnderlay {
                            drawMapUnderlay(mapUnderlay, context: dataContext, size: size)
                        }
                        if let frame {
                            drawPPI(frame, context: dataContext, size: size)
                        }
                        drawOverlay(context: dataContext, size: size)
                    }
                }
                .frame(width: proxy.size.width, height: proxy.size.height)
                .clipped()
                .contentShape(Rectangle())
                .gesture(plotDragGesture(size: proxy.size))
                .simultaneousGesture(plotMagnificationGesture(size: proxy.size))

                if viewport.isZoomed {
                    Button {
                        resetRadarViewport()
                    } label: {
                        Image(systemName: "arrow.counterclockwise")
                            .font(.callout.weight(.semibold))
                            .frame(width: 34, height: 34)
                            .foregroundStyle(.white)
                            .background(Circle().fill(Color.secondary.opacity(0.85)))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Reset map zoom")
                    .position(x: max(27, proxy.size.width - 27), y: 27)
                }

                if let identifyResult {
                    PlotIdentifyBadge(
                        identifyResult: identifyResult,
                        isDetailed: showDetailedIdentifyReadout,
                        pointerFields: pointerFields
                    )
                }

            }
            .clipped()
        }
        .accessibilityLabel("PPI radar plot")
        .onChange(of: viewportResetKey) { newKey in
            updateViewportResetKey(newKey)
        }
        .accessibilityAction(named: "Reset map zoom") {
            resetRadarViewport()
        }
    }

    private var viewportResetKey: String? {
        guard let metadata = frame?.metadata else { return nil }
        return [
            metadata.radar,
            String(format: "%.5f", metadata.latitude),
            String(format: "%.5f", metadata.longitude),
            String(format: "%.0f", metadata.maxRangeM),
            String(metadata.nbins),
            String(metadata.nrays),
        ].joined(separator: "|")
    }

    private func updateViewportResetKey(_ newKey: String?) {
        guard let newKey else { return }
        defer { lastViewportResetKey = newKey }
        guard let lastViewportResetKey else { return }
        if lastViewportResetKey != newKey {
            resetRadarViewport()
        }
    }

    private func activeViewport(size: CGSize) -> RadarViewport {
        let scale = clampedScale(viewportScale * gestureScale)
        let proposedOffset = CGSize(
            width: viewportOffset.width + gestureOffset.width,
            height: viewportOffset.height + gestureOffset.height
        )
        return RadarViewport(
            scale: scale,
            offset: clampedOffset(proposedOffset, scale: scale, size: size)
        )
    }

    private func plotDragGesture(size: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 0, coordinateSpace: .local)
            .updating($gestureOffset) { value, state, _ in
                guard isPan(value.translation) || viewportScale > 1.001 else { return }
                state = value.translation
            }
            .onEnded { value in
                let moved = isPan(value.translation)
                if !moved && !suppressIdentifyAfterPinch {
                    let viewport = activeViewport(size: size)
                    let plotPoint = untransformedPoint(value.location, viewport: viewport, size: size)
                    guard let frame, let bin = binAt(plotPoint, size: size, frame: frame) else { return }
                    onIdentify(bin.row, bin.column)
                    return
                }

                guard moved || viewportScale > 1.001 else { return }
                viewportOffset = clampedOffset(
                    CGSize(
                        width: viewportOffset.width + value.translation.width,
                        height: viewportOffset.height + value.translation.height
                    ),
                    scale: viewportScale,
                    size: size
                )
            }
    }

    private func plotMagnificationGesture(size: CGSize) -> some Gesture {
        MagnificationGesture()
            .updating($gestureScale) { value, state, _ in
                state = value
            }
            .onChanged { _ in
                suppressIdentifyAfterPinch = true
            }
            .onEnded { value in
                viewportScale = clampedScale(viewportScale * value)
                viewportOffset = clampedOffset(viewportOffset, scale: viewportScale, size: size)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                    suppressIdentifyAfterPinch = false
                }
            }
    }

    private func resetRadarViewport() {
        viewportScale = 1
        viewportOffset = .zero
    }

    private func applyDataViewport(_ viewport: RadarViewport, to context: inout GraphicsContext, size: CGSize) {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        context.translateBy(x: viewport.offset.width, y: viewport.offset.height)
        context.translateBy(x: center.x, y: center.y)
        context.scaleBy(x: viewport.scale, y: viewport.scale)
        context.translateBy(x: -center.x, y: -center.y)
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

    private func untransformedPoint(_ point: CGPoint, viewport: RadarViewport, size: CGSize) -> CGPoint {
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        return CGPoint(
            x: ((point.x - center.x - viewport.offset.width) / viewport.scale) + center.x,
            y: ((point.y - center.y - viewport.offset.height) / viewport.scale) + center.y
        )
    }

    private func clampedScale(_ scale: CGFloat) -> CGFloat {
        min(max(scale, 1), maximumRadarZoomScale)
    }

    private func clampedOffset(_ offset: CGSize, scale: CGFloat, size: CGSize) -> CGSize {
        guard scale > 1.001 else { return .zero }
        let horizontalLimit = max(0, size.width * (scale - 1) / 2)
        let verticalLimit = max(0, size.height * (scale - 1) / 2)
        return CGSize(
            width: min(max(offset.width, -horizontalLimit), horizontalLimit),
            height: min(max(offset.height, -verticalLimit), verticalLimit)
        )
    }

    private func isPan(_ translation: CGSize) -> Bool {
        hypot(translation.width, translation.height) > 8
    }
}

private struct RadarViewport {
    var scale: CGFloat
    var offset: CGSize

    var isZoomed: Bool {
        scale > 1.001 || abs(offset.width) > 0.5 || abs(offset.height) > 0.5
    }
}

private struct LightweightPPIPlotView: View {
    var frame: PPIFrame?
    var identifyResult: IdentifyResult?
    var pointerFields: PointerFieldPreferences

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

                if let identifyResult {
                    PlotIdentifyBadge(identifyResult: identifyResult, isDetailed: false, pointerFields: pointerFields)
                }
            }
        }
        .accessibilityLabel("PPI radar plot")
    }
}

private struct PlotIdentifyBadge: View {
    var identifyResult: IdentifyResult
    var isDetailed: Bool
    var pointerFields: PointerFieldPreferences

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if pointerFields.value {
                    Text(identifyResult.valueDescription)
                    .font(.caption.weight(.semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(identifyResult.valueStatusText)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(identifyResult.maskedByNoiseFloor ? .orange : .secondary)
                    .lineLimit(1)
            }

            if isDetailed {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    if pointerFields.range { ProbeReadoutRow(label: "Range", value: identifyResult.rangeText) }
                    if pointerFields.azimuth { ProbeReadoutRow(label: "Azimuth", value: identifyResult.azimuthText) }
                    if pointerFields.beamHeight { ProbeReadoutRow(label: "Height", value: identifyResult.heightText) }
                    if pointerFields.coordinates { ProbeReadoutRow(label: "Lat, lon", value: identifyResult.coordinateText) }
                    if pointerFields.elevation { ProbeReadoutRow(label: "Elevation", value: identifyResult.elevationText) }
                    if pointerFields.rawValue { ProbeReadoutRow(label: "Raw", value: identifyResult.rawValueText) }
                    if pointerFields.gateIndices {
                        ProbeReadoutRow(label: "Gate", value: "row \(identifyResult.row), col \(identifyResult.column)")
                    }
                }
            } else {
                Text(identifyResult.compactDescription)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(.primary)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .padding(10)
        .frame(maxWidth: isDetailed ? 320 : 240, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityIdentifier("PlotIdentifyBadge")
    }
}

private struct ProbeReadoutRow: View {
    var label: String
    var value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(width: 58, alignment: .leading)
            Text(value)
                .font(.caption2.monospacedDigit())
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
    }
}

private struct ColorBarModel: Hashable {
    var quantity: String
    var palette: String
    var scaleMin: Double
    var scaleMax: Double

    init?(frame: PPIFrame) {
        guard let scaleMin = frame.stats.scaleMin,
              let scaleMax = frame.stats.scaleMax,
              scaleMin.isFinite,
              scaleMax.isFinite,
              scaleMin != scaleMax else {
            return nil
        }
        self.quantity = frame.metadata.quantity
        self.palette = frame.palette
        self.scaleMin = scaleMin
        self.scaleMax = scaleMax
    }

    var unit: String {
        quantityUnit(quantity)
    }

    var title: String {
        "\(quantity) · \(palette)"
    }

    var midpoint: Double {
        scaleMin + (scaleMax - scaleMin) / 2
    }

    var gradientColors: [Color] {
        stride(from: 0, through: 255, by: 17).map {
            PaletteEngine.color(UInt8($0), palette: palette)
        }
    }

    func label(_ value: Double) -> String {
        let span = abs(scaleMax - scaleMin)
        let number: String
        if span >= 50 {
            number = String(format: "%.0f", value)
        } else if span >= 5 {
            number = String(format: "%.1f", value)
        } else {
            number = String(format: "%.2f", value)
        }
        return unit.isEmpty ? number : "\(number) \(unit)"
    }
}

private struct PlotColorBar: View {
    var model: ColorBarModel

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(model.title)
                .font(.caption2.weight(.semibold))
                .lineLimit(1)
                .frame(width: 92, alignment: .leading)

            VStack(alignment: .leading, spacing: 4) {
                LinearGradient(
                    colors: model.gradientColors,
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .frame(height: 9)
                .clipShape(Capsule())

                HStack {
                    Text(model.label(model.scaleMin))
                    Spacer(minLength: 8)
                    Text(model.label(model.midpoint))
                    Spacer(minLength: 8)
                    Text(model.label(model.scaleMax))
                }
                .font(.caption2)
                .monospacedDigit()
            }
        }
        .foregroundStyle(.primary)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("PlotColorBar")
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

        let fileURL = try uniqueFileURL(
            in: downloadsDirectory(),
            baseName: fileName(for: frame),
            fileExtension: "png"
        )
        try data.write(to: fileURL, options: .atomic)
        return fileURL
    }

    static func writeMP4(
        frames: [PPIFrame],
        opacity: Double,
        mapUnderlay: UIImage? = nil,
        mapOpacity: Double = 0.35,
        size: CGSize = CGSize(width: 900, height: 900),
        framesPerSecond: Int32 = 8,
        isCancelled: () -> Bool = { false }
    ) throws -> URL {
        guard let firstFrame = frames.first else {
            throw PPIImageExportError.noFrames
        }
        guard !isCancelled() else {
            throw VideoExportError.backgroundTimeExpired
        }

        let sequenceWriter = try MP4SequenceWriter(firstFrame: firstFrame, size: size, framesPerSecond: framesPerSecond)
        do {
            for frame in frames {
                if isCancelled() {
                    throw VideoExportError.backgroundTimeExpired
                }
                try sequenceWriter.append(
                    frame: frame,
                    opacity: opacity,
                    mapUnderlay: mapUnderlay,
                    mapOpacity: mapOpacity,
                    isCancelled: isCancelled
                )
            }
        } catch {
            sequenceWriter.cancel()
            throw error
        }

        guard !isCancelled() else {
            sequenceWriter.cancel()
            throw VideoExportError.backgroundTimeExpired
        }
        return try sequenceWriter.finish()
    }

    static func renderVideoFrameImage(
        frame: PPIFrame,
        opacity: Double,
        mapUnderlay: UIImage? = nil,
        mapOpacity: Double = 0.35,
        size: CGSize = CGSize(width: 900, height: 900)
    ) -> UIImage {
        renderImage(frame: frame, opacity: opacity, mapUnderlay: mapUnderlay, mapOpacity: mapOpacity, size: size)
    }

    final class MP4SequenceWriter {
        private let writer: AVAssetWriter
        private let input: AVAssetWriterInput
        private let adaptor: AVAssetWriterInputPixelBufferAdaptor
        private let frameDuration: CMTime
        private let size: CGSize
        private let fileURL: URL
        private var isFinished = false
        private var rasterGeometry: RasterGeometry?

        private(set) var frameCount = 0

        convenience init(firstFrame: PPIFrame, size: CGSize = CGSize(width: 900, height: 900), framesPerSecond: Int32 = 8) throws {
            try self.init(baseName: PPIImageExporter.fileName(for: firstFrame) + "-sequence", size: size, framesPerSecond: framesPerSecond)
        }

        init(baseName: String, size: CGSize = CGSize(width: 900, height: 900), framesPerSecond: Int32 = 8) throws {
            let outputURL = try PPIImageExporter.uniqueFileURL(
                in: PPIImageExporter.downloadsDirectory(),
                baseName: baseName,
                fileExtension: "mp4"
            )
            let assetWriter = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
            let duration = CMTime(value: 1, timescale: framesPerSecond)

            let width = Int(size.width)
            let height = Int(size.height)
            let settings: [String: Any] = [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: width,
                AVVideoHeightKey: height,
            ]
            let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
            videoInput.expectsMediaDataInRealTime = false
            let attributes: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ]
            let pixelAdaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: videoInput, sourcePixelBufferAttributes: attributes)
            guard assetWriter.canAdd(videoInput) else {
                throw PPIImageExportError.videoWriterFailed("The MP4 writer could not add its video input.")
            }
            assetWriter.add(videoInput)
            assetWriter.startWriting()
            assetWriter.startSession(atSourceTime: .zero)

            self.size = size
            self.fileURL = outputURL
            self.writer = assetWriter
            self.input = videoInput
            self.adaptor = pixelAdaptor
            self.frameDuration = duration
        }

        func append(
            frame: PPIFrame,
            opacity: Double,
            mapUnderlay: UIImage?,
            mapOpacity: Double,
            isCancelled: () -> Bool = { false }
        ) throws {
            guard !isFinished else {
                throw PPIImageExportError.videoWriterFailed("The MP4 writer is already finished.")
            }
            guard !isCancelled() else {
                throw VideoExportError.backgroundTimeExpired
            }
            _ = try appendDirect(
                frame: frame,
                opacity: opacity,
                mapUnderlay: mapUnderlay,
                mapOpacity: mapOpacity,
                isCancelled: isCancelled
            )
        }

        func appendDirect(
            frame: PPIFrame,
            opacity: Double,
            mapUnderlay: UIImage?,
            mapOpacity: Double,
            isCancelled: () -> Bool = { false }
        ) throws -> VideoFrameWriteTiming {
            guard !isFinished else {
                throw PPIImageExportError.videoWriterFailed("The MP4 writer is already finished.")
            }
            guard !isCancelled() else {
                throw VideoExportError.backgroundTimeExpired
            }
            try waitUntilReady(isCancelled: isCancelled)
            let drawStart = Date()
            let buffer = try PPIImageExporter.pixelBuffer(size: size, pool: adaptor.pixelBufferPool)
            let geometry = PPIImageExporter.rasterGeometry(for: frame, size: size, cached: &rasterGeometry)
            try PPIImageExporter.draw(
                frame: frame,
                opacity: opacity,
                mapUnderlay: mapUnderlay,
                mapOpacity: mapOpacity,
                into: buffer,
                size: size,
                geometry: geometry
            )
            let drawSeconds = Date().timeIntervalSince(drawStart)
            guard !isCancelled() else {
                throw VideoExportError.backgroundTimeExpired
            }
            let encodeStart = Date()
            let presentationTime = CMTimeMultiply(frameDuration, multiplier: Int32(frameCount))
            if !adaptor.append(buffer, withPresentationTime: presentationTime) {
                throw PPIImageExportError.videoWriterFailed(writer.error?.localizedDescription ?? "")
            }
            frameCount += 1
            return VideoFrameWriteTiming(
                drawSeconds: drawSeconds,
                encodeSeconds: Date().timeIntervalSince(encodeStart)
            )
        }

        func append(image: UIImage, isCancelled: () -> Bool = { false }) throws {
            guard !isFinished else {
                throw PPIImageExportError.videoWriterFailed("The MP4 writer is already finished.")
            }
            guard !isCancelled() else {
                throw VideoExportError.backgroundTimeExpired
            }
            try waitUntilReady(isCancelled: isCancelled)
            let buffer = try PPIImageExporter.pixelBuffer(from: image, size: size)
            let presentationTime = CMTimeMultiply(frameDuration, multiplier: Int32(frameCount))
            if !adaptor.append(buffer, withPresentationTime: presentationTime) {
                throw PPIImageExportError.videoWriterFailed(writer.error?.localizedDescription ?? "")
            }
            frameCount += 1
        }

        private func waitUntilReady(isCancelled: () -> Bool) throws {
            while !input.isReadyForMoreMediaData {
                if isCancelled() {
                    throw VideoExportError.backgroundTimeExpired
                }
                Thread.sleep(forTimeInterval: 0.005)
            }
        }

        func finish() throws -> URL {
            guard !isFinished else { return fileURL }
            isFinished = true
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

        func cancel(removeFile: Bool = true) {
            guard !isFinished else { return }
            isFinished = true
            writer.cancelWriting()
            if removeFile {
                try? FileManager.default.removeItem(at: fileURL)
            }
        }
    }

    private struct RasterGeometry {
        var key: String
        var rows: Int
        var columns: Int
        var radius: CGFloat
        var center: CGPoint
        var startAngles: [CGFloat]
        var endAngles: [CGFloat]
        var innerRadii: [CGFloat]
        var outerRadii: [CGFloat]

        init(frame: PPIFrame, size: CGSize) {
            let resolvedRows = max(frame.rows, 1)
            let resolvedColumns = max(frame.columns, 1)
            let resolvedRadius = min(size.width, size.height) * 0.46
            rows = resolvedRows
            columns = resolvedColumns
            key = "\(Int(size.width))x\(Int(size.height)):\(resolvedRows)x\(resolvedColumns)"
            radius = resolvedRadius
            center = CGPoint(x: size.width / 2, y: size.height / 2)
            let angleStep = 360.0 / Double(resolvedRows)
            startAngles = (0..<resolvedRows).map { row in
                CGFloat((Double(row) * angleStep - 90) * Double.pi / 180)
            }
            endAngles = (0..<resolvedRows).map { row in
                CGFloat((Double(row + 1) * angleStep - 90) * Double.pi / 180)
            }
            innerRadii = (0..<resolvedColumns).map { column in
                resolvedRadius * CGFloat(column) / CGFloat(resolvedColumns)
            }
            outerRadii = (0..<resolvedColumns).map { column in
                resolvedRadius * CGFloat(column + 1) / CGFloat(resolvedColumns)
            }
        }
    }

    private static func rasterGeometry(for frame: PPIFrame, size: CGSize, cached: inout RasterGeometry?) -> RasterGeometry {
        let candidateKey = "\(Int(size.width))x\(Int(size.height)):\(max(frame.rows, 1))x\(max(frame.columns, 1))"
        if let cached, cached.key == candidateKey {
            return cached
        }
        let geometry = RasterGeometry(frame: frame, size: size)
        cached = geometry
        return geometry
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
        into pixelBuffer: CVPixelBuffer,
        size: CGSize,
        geometry: RasterGeometry
    ) throws {
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: baseAddress,
            width: Int(size.width),
            height: Int(size.height),
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        ) else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        UIGraphicsPushContext(context)
        draw(
            frame: frame,
            opacity: opacity,
            mapUnderlay: mapUnderlay,
            mapOpacity: mapOpacity,
            in: context,
            size: size,
            geometry: geometry
        )
        UIGraphicsPopContext()
    }

    private static func draw(
        frame: PPIFrame,
        opacity: Double,
        mapUnderlay: UIImage?,
        mapOpacity: Double,
        in context: CGContext,
        size: CGSize,
        geometry: RasterGeometry? = nil
    ) {
        let rect = CGRect(origin: .zero, size: size)
        UIColor.systemBackground.setFill()
        context.fill(rect)

        let geometry = geometry ?? RasterGeometry(frame: frame, size: size)
        let radius = geometry.radius
        let center = geometry.center
        let rows = geometry.rows
        let columns = geometry.columns

        if let mapUnderlay {
            let mapRect = CGRect(origin: .zero, size: size)
            mapUnderlay.draw(in: mapRect, blendMode: .normal, alpha: mapOpacity)
        }

        for row in 0..<rows {
            let start = geometry.startAngles[row]
            let end = geometry.endAngles[row]
            for column in 0..<columns {
                let index = frame.index(row: row, column: column)
                guard frame.valid[index] else { continue }
                let inner = geometry.innerRadii[column]
                let outer = geometry.outerRadii[column]
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
        let pixelBuffer = try pixelBuffer(size: size, pool: nil)
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: baseAddress,
            width: Int(size.width),
            height: Int(size.height),
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

    private static func pixelBuffer(size: CGSize, pool: CVPixelBufferPool?) throws -> CVPixelBuffer {
        let width = Int(size.width)
        let height = Int(size.height)
        var pixelBuffer: CVPixelBuffer?
        let status: CVReturn
        if let pool {
            status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &pixelBuffer)
        } else {
            status = CVPixelBufferCreate(
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
        }
        guard status == kCVReturnSuccess, let pixelBuffer else {
            throw PPIImageExportError.cannotCreatePixelBuffer
        }
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

    private static func downloadsDirectory() throws -> URL {
        let documents = try FileManager.default.url(
            for: .documentDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let downloads = documents.appendingPathComponent("Downloads", isDirectory: true)
        try FileManager.default.createDirectory(at: downloads, withIntermediateDirectories: true, attributes: nil)
        return downloads
    }

    static func videoExportJobsDirectory() throws -> URL {
        let jobs = try downloadsDirectory().appendingPathComponent(".video-export-jobs", isDirectory: true)
        try FileManager.default.createDirectory(at: jobs, withIntermediateDirectories: true, attributes: nil)
        return jobs
    }

    private static func uniqueFileURL(in directory: URL, baseName: String, fileExtension: String) throws -> URL {
        var candidate = directory
            .appendingPathComponent(baseName)
            .appendingPathExtension(fileExtension)
        var suffix = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = directory
                .appendingPathComponent("\(baseName)-\(suffix)")
                .appendingPathExtension(fileExtension)
            suffix += 1
        }
        return candidate
    }
}

private extension View {
    func panelStyle() -> some View {
        self
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppUI.panelBackground, in: RoundedRectangle(cornerRadius: AppUI.panelRadius))
            .overlay(
                RoundedRectangle(cornerRadius: AppUI.panelRadius)
                    .stroke(AppUI.hairline, lineWidth: 1)
            )
    }
}

private extension RadarGridMetadata {
    var statusDisplayLine: String {
        "Rendered · \(displayRadarName) · \(formattedDateText) · \(pulse) \(time) · \(quantity) · \(elevationText)"
    }

    var statusPrimaryLine: String {
        "\(displayRadarName) · \(formattedDateText)"
    }

    var statusSecondaryLine: String {
        "\(pulse) \(time) · \(quantity) · \(elevationText)"
    }

    var radarDisplayLine: String {
        "\(displayRadarName) \(formattedDateText) \(quantity)"
    }

    var sweepDisplayLine: String {
        "\(pulse) \(time) \(elevationText)"
    }

    private var displayRadarName: String {
        radar
            .split(separator: "-")
            .map { part in part.prefix(1).uppercased() + part.dropFirst() }
            .joined(separator: " ")
    }

    private var formattedDateText: String {
        guard date.count == 8 else { return date }
        let year = date.prefix(4)
        let month = date.dropFirst(4).prefix(2)
        let day = date.suffix(2)
        return "\(year)-\(month)-\(day)"
    }

    private var elevationText: String {
        elevationDeg.map { String(format: "%.2f°", $0) } ?? "elevation n/a"
    }
}
