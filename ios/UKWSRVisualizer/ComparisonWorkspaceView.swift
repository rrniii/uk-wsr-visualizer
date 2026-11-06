import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct ComparisonWorkspaceView: View {
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
