import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct RadarDisplayView: View {
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

struct LaunchLoadingView: View {
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

struct ScanHeaderBar: View {
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
