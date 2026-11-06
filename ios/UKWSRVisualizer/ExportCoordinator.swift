import Combine
import Foundation
import UIKit

struct VideoExportResumeStatus: Equatable {
    var completed: Int
    var requested: Int

    var remaining: Int {
        max(0, requested - completed)
    }

    var fractionText: String {
        "\(completed) / \(requested)"
    }
}

@MainActor
final class ExportCoordinator: ObservableObject {
    @Published private(set) var exportedPNGURL: URL?
    @Published private(set) var exportedVideoURL: URL?
    @Published private(set) var exportMessage: String?
    @Published private(set) var resumeStatus: VideoExportResumeStatus?
    @Published var videoExportMode: VideoExportMode = .fast

    private let model: VisualizerViewModel
    private var videoExportHadFailure = false
    private var exportTask: Task<Void, Never>?

    init(model: VisualizerViewModel) {
        self.model = model
    }

    func selectionChanged() {
        exportedPNGURL = nil
        exportedVideoURL = nil
        exportMessage = nil
        videoExportHadFailure = false
    }

    func createPNG() {
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

    var videoButtonTitle: String {
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

    var runningExportMessage: String {
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

    var resumeLookupKey: String {
        videoExportSignature() + "|times=" + model.availableTimes.joined(separator: ",")
    }

    @MainActor
    func refreshResumeStatus() async {
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

    func clearResumeFrames() {
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
            String(filters.receiverNoiseEnabled),
            formatted(filters.receiverNoiseMarginDb),
            formatted(filters.receiverNoiseSqiMax),
            String(filters.receiverNoiseMinBadMoments),
            String(filters.ciEvidenceEnabled),
            String(filters.textureCleanupEnabled),
            String(filters.companionQcEnabled),
            String(filters.staticClutterEnabled),
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
            formatted(filters.backgroundCurrentVradAbsMax),
            String(filters.backgroundRequireTrainingDiversity),
            String(filters.backgroundMinTrainingDates),
            String(filters.backgroundMinTrainingSpanDays),
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

    func createVideo() {
        guard exportTask == nil else { return }
        let model = model
        exportedVideoURL = nil
        exportMessage = nil
        videoExportHadFailure = false
        let requestedMode = activeExportMode
        let backgroundSession = BackgroundExportSession(name: "UK WSR MP4 Export") {
            model.cancelVideoExportForBackgroundExpiration()
        }
        exportTask = Task {
            var sequenceWriter: PPIImageExporter.MP4SequenceWriter?
            var frameStore: VideoExportFrameStore?
            defer {
                model.isExportingVideo = false
                exportTask = nil
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
                    sequenceWriter = nil
                    let skipped = summary.skippedFrames > 0 ? " Skipped \(summary.skippedFrames)." : ""
                    exportMessage = "\(plan.mode.statusName) MP4 saved to Files > On My iPhone > UK WSR > Downloads.\(skipped) \(summary.metrics.summaryText)"
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
                let didComplete = !summary.stoppedEarly &&
                    !backgroundSession.isExpired &&
                    encodedFrames == exportTimes.count &&
                    store.completedTimes.count == exportTimes.count
                if didComplete {
                    store.clear()
                    exportMessage = "Resume-safe MP4 saved to Files > On My iPhone > UK WSR > Downloads. \(summary.metrics.summaryText)"
                    videoExportHadFailure = false
                } else {
                    exportMessage = "Partial MP4 saved to Files > On My iPhone > UK WSR > Downloads (\(encodedFrames) of \(exportTimes.count) frames). Tap Resume MP4 later to finish the full video. \(summary.metrics.summaryText)"
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
