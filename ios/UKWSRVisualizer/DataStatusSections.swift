import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct MetadataSection: View {
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

struct RawCacheSection: View {
    @ObservedObject var model: VisualizerViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader("Raw Cache", systemImage: "externaldrive") {
                MetadataPill(text: model.cacheStatus.displayText)
            }

            HStack {
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

            if let performance = model.lastRenderPerformance {
                LabeledContent("Latest render", value: performance.displayText)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            Toggle(isOn: $model.showDataID) {
                Text("Show Data ID")
                    .font(.caption)
            }
        }
        .panelStyle()
    }
}
