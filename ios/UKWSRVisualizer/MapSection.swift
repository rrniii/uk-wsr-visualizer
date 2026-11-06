import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct MapSection: View {
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
