import SwiftUI

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

struct ExportSection: View {
    @ObservedObject var model: VisualizerViewModel
    @StateObject private var coordinator: ExportCoordinator

    init(model: VisualizerViewModel) {
        self.model = model
        _coordinator = StateObject(wrappedValue: ExportCoordinator(model: model))
    }

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
                    coordinator.createPNG()
                } label: {
                    Label("Create PNG", systemImage: "photo")
                }
                .buttonStyle(.bordered)
                .disabled(model.frame == nil)

                Button {
                    coordinator.createVideo()
                } label: {
                    Label(coordinator.videoButtonTitle, systemImage: "film")
                }
                .buttonStyle(.bordered)
                .disabled(model.frame == nil || model.availableTimes.count < 2 || model.isExportingVideo)

                if coordinator.resumeStatus != nil {
                    Button(role: .destructive) {
                        coordinator.clearResumeFrames()
                    } label: {
                        Label("Clear saved", systemImage: "trash")
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .disabled(model.isExportingVideo)
                }

                if let exportedPNGURL = coordinator.exportedPNGURL {
                    ShareLink(item: exportedPNGURL) {
                        Label("Share PNG", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }

                if let exportedVideoURL = coordinator.exportedVideoURL {
                    ShareLink(item: exportedVideoURL) {
                        Label("Share MP4", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }

            Picker("MP4 mode", selection: $coordinator.videoExportMode) {
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
                    resumeStatus: coordinator.resumeStatus,
                    message: coordinator.runningExportMessage
                )
            } else if let resumeStatus = coordinator.resumeStatus {
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
                    Text("Keeping the phone awake while exporting.")
                        .foregroundStyle(.secondary)
                }
                .font(.caption)
            }

            if let exportMessage = coordinator.exportMessage {
                Text(exportMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .panelStyle()
        .onChange(of: model.frame?.id) { _ in
            coordinator.selectionChanged()
        }
        .task(id: coordinator.resumeLookupKey) {
            await coordinator.refreshResumeStatus()
        }
    }

}
