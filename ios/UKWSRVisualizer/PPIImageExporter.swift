import AVFoundation
import Foundation
import UIKit

enum PPIImageExportError: LocalizedError {
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

struct PPIImageExporter {
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
