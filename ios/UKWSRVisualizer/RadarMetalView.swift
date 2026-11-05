import MetalKit
import SwiftUI

struct MetalPPIDataView: UIViewRepresentable {
    var frame: PPIFrame
    var opacity: Double

    static var isAvailable: Bool {
        MTLCreateSystemDefaultDevice() != nil
    }

    func makeCoordinator() -> RadarMetalCoordinator {
        RadarMetalCoordinator()
    }

    func makeUIView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: MTLCreateSystemDefaultDevice())
        view.isOpaque = false
        view.backgroundColor = .clear
        view.clearColor = MTLClearColorMake(0, 0, 0, 0)
        view.colorPixelFormat = .bgra8Unorm
        view.framebufferOnly = true
        view.enableSetNeedsDisplay = true
        view.isPaused = true
        view.preferredFramesPerSecond = 60
        context.coordinator.configure(view)
        context.coordinator.update(frame: frame, opacity: opacity, in: view)
        return view
    }

    func updateUIView(_ view: MTKView, context: Context) {
        context.coordinator.update(frame: frame, opacity: opacity, in: view)
    }

    static func dismantleUIView(_ view: MTKView, coordinator: RadarMetalCoordinator) {
        view.delegate = nil
        coordinator.releaseResources()
    }
}

final class RadarMetalCoordinator: NSObject, MTKViewDelegate {
    private struct Uniforms {
        var opacity: Float
        var plotRadius: Float
    }

    private var commandQueue: MTLCommandQueue?
    private var pipeline: MTLRenderPipelineState?
    private var dataTexture: MTLTexture?
    private var paletteTexture: MTLTexture?
    private var frameID: UUID?
    private var paletteName = ""
    private var opacity: Float = 1

    func configure(_ view: MTKView) {
        guard let device = view.device else { return }
        commandQueue = device.makeCommandQueue()
        pipeline = makePipeline(device: device, pixelFormat: view.colorPixelFormat)
        view.delegate = self
    }

    func update(frame: PPIFrame, opacity: Double, in view: MTKView) {
        let resolvedOpacity = Float(clamp(opacity, 0, 1))
        var needsDisplay = resolvedOpacity != self.opacity
        self.opacity = resolvedOpacity

        if frameID != frame.id {
            dataTexture = makeDataTexture(frame: frame, device: view.device)
            frameID = frame.id
            needsDisplay = true
        }
        if paletteName != frame.palette || paletteTexture == nil {
            paletteTexture = makePaletteTexture(palette: frame.palette, device: view.device)
            paletteName = frame.palette
            needsDisplay = true
        }
        if needsDisplay {
            view.setNeedsDisplay()
        }
    }

    func releaseResources() {
        dataTexture = nil
        paletteTexture = nil
        pipeline = nil
        commandQueue = nil
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        view.setNeedsDisplay()
    }

    func draw(in view: MTKView) {
        guard let commandQueue,
              let pipeline,
              let dataTexture,
              let paletteTexture,
              let drawable = view.currentDrawable,
              let descriptor = view.currentRenderPassDescriptor,
              let commandBuffer = commandQueue.makeCommandBuffer(),
              let encoder = commandBuffer.makeRenderCommandEncoder(descriptor: descriptor) else {
            return
        }

        var uniforms = Uniforms(opacity: opacity, plotRadius: 0.92)
        encoder.setRenderPipelineState(pipeline)
        encoder.setFragmentTexture(dataTexture, index: 0)
        encoder.setFragmentTexture(paletteTexture, index: 1)
        encoder.setFragmentBytes(&uniforms, length: MemoryLayout<Uniforms>.stride, index: 0)
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6)
        encoder.endEncoding()
        commandBuffer.present(drawable)
        commandBuffer.commit()
    }

    private func makeDataTexture(frame: PPIFrame, device: MTLDevice?) -> MTLTexture? {
        guard let device, frame.rows > 0, frame.columns > 0 else { return nil }
        let descriptor = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: .rg8Unorm,
            width: frame.columns,
            height: frame.rows,
            mipmapped: false
        )
        descriptor.usage = [.shaderRead]
        guard let texture = device.makeTexture(descriptor: descriptor) else { return nil }

        var bytes = [UInt8](repeating: 0, count: frame.rows * frame.columns * 2)
        for index in frame.scaled.indices {
            bytes[index * 2] = frame.scaled[index]
            bytes[index * 2 + 1] = frame.valid[index] ? 255 : 0
        }
        bytes.withUnsafeBytes { rawBytes in
            guard let baseAddress = rawBytes.baseAddress else { return }
            texture.replace(
                region: MTLRegionMake2D(0, 0, frame.columns, frame.rows),
                mipmapLevel: 0,
                withBytes: baseAddress,
                bytesPerRow: frame.columns * 2
            )
        }
        return texture
    }

    private func makePaletteTexture(palette: String, device: MTLDevice?) -> MTLTexture? {
        guard let device else { return nil }
        let descriptor = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: .rgba8Unorm,
            width: 256,
            height: 1,
            mipmapped: false
        )
        descriptor.usage = [.shaderRead]
        guard let texture = device.makeTexture(descriptor: descriptor) else { return nil }

        var bytes = [UInt8](repeating: 0, count: 256 * 4)
        for value in 0..<256 {
            let rgba = PaletteEngine.rgba(UInt8(value), palette: palette)
            bytes[value * 4] = UInt8(clamp(round(rgba.red), 0, 255))
            bytes[value * 4 + 1] = UInt8(clamp(round(rgba.green), 0, 255))
            bytes[value * 4 + 2] = UInt8(clamp(round(rgba.blue), 0, 255))
            bytes[value * 4 + 3] = 255
        }
        bytes.withUnsafeBytes { rawBytes in
            guard let baseAddress = rawBytes.baseAddress else { return }
            texture.replace(
                region: MTLRegionMake2D(0, 0, 256, 1),
                mipmapLevel: 0,
                withBytes: baseAddress,
                bytesPerRow: 256 * 4
            )
        }
        return texture
    }

    private func makePipeline(device: MTLDevice, pixelFormat: MTLPixelFormat) -> MTLRenderPipelineState? {
        do {
            guard let library = device.makeDefaultLibrary() else { return nil }
            let descriptor = MTLRenderPipelineDescriptor()
            descriptor.vertexFunction = library.makeFunction(name: "radar_vertex")
            descriptor.fragmentFunction = library.makeFunction(name: "radar_fragment")
            descriptor.colorAttachments[0].pixelFormat = pixelFormat
            descriptor.colorAttachments[0].isBlendingEnabled = true
            descriptor.colorAttachments[0].sourceRGBBlendFactor = .sourceAlpha
            descriptor.colorAttachments[0].destinationRGBBlendFactor = .oneMinusSourceAlpha
            descriptor.colorAttachments[0].sourceAlphaBlendFactor = .one
            descriptor.colorAttachments[0].destinationAlphaBlendFactor = .oneMinusSourceAlpha
            return try device.makeRenderPipelineState(descriptor: descriptor)
        } catch {
            return nil
        }
    }
}
