import Foundation
import SwiftUI
import UIKit

struct PPIPlotView: View {
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
                    Color(.systemBackground)

                    ZStack {
                        if let mapUnderlay {
                            Image(uiImage: mapUnderlay)
                                .resizable()
                                .interpolation(.high)
                                .frame(width: proxy.size.width, height: proxy.size.height)
                                .opacity(mapOpacity)
                        }

                        if let frame {
                            if MetalPPIDataView.isAvailable {
                                MetalPPIDataView(frame: frame, opacity: opacity)
                                    .frame(width: proxy.size.width, height: proxy.size.height)
                            } else {
                                Canvas { context, size in
                                    drawPPI(frame, context: context, size: size)
                                }
                            }
                        }

                        Canvas { context, size in
                            drawOverlay(context: context, size: size)
                        }
                    }
                    .scaleEffect(viewport.scale)
                    .offset(viewport.offset)
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

struct LightweightPPIPlotView: View {
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
                    PlotIdentifyBadge(
                        identifyResult: identifyResult,
                        isDetailed: false,
                        pointerFields: pointerFields
                    )
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
                        ProbeReadoutRow(
                            label: "Gate",
                            value: "\(identifyResult.row), \(identifyResult.column)"
                        )
                    }
                }
            } else if pointerFields.range || pointerFields.azimuth || pointerFields.beamHeight {
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

struct ColorBarModel: Hashable {
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

struct PlotColorBar: View {
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
