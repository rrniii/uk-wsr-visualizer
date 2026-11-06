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
