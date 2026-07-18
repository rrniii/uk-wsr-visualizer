import Foundation
import UIKit

struct ExportedArtifact: Identifiable {
    var label: String
    var url: URL
    var id: String { url.path }
}

enum GeospatialExporter {
    private struct Bounds {
        var west: Double
        var south: Double
        var east: Double
        var north: Double
    }

    private struct MetadataPayload: Encodable {
        var version = 1
        var generatedAt: String
        var coordinateMode = "screen_view"
        var radar: String
        var date: String
        var pulse: String
        var time: String
        var quantity: String
        var dataset: String
        var latitude: Double
        var longitude: Double
        var elevationDeg: Double?
        var rows: Int
        var columns: Int
        var validGateCount: Int
        var dataFingerprint: String
        var bounds: [Double]

        enum CodingKeys: String, CodingKey {
            case version
            case generatedAt = "generated_at"
            case coordinateMode = "coordinate_mode"
            case radar, date, pulse, time, quantity, dataset, latitude, longitude
            case elevationDeg = "elevation_deg"
            case rows, columns
            case validGateCount = "valid_gate_count"
            case dataFingerprint = "data_fingerprint"
            case bounds
        }
    }

    static func writeCompanions(pngURL: URL, frame: PPIFrame) throws -> [ExportedArtifact] {
        guard let image = UIImage(contentsOfFile: pngURL.path), let cgImage = image.cgImage else {
            throw WorkspaceDocumentError.noSelection
        }
        let bounds = geographicBounds(frame: frame)
        let stem = pngURL.deletingPathExtension().lastPathComponent
        let directory = pngURL.deletingLastPathComponent()

        let metadataURL = directory.appendingPathComponent(stem + ".metadata.json")
        let metadata = MetadataPayload(
            generatedAt: ISO8601DateFormatter().string(from: Date()),
            radar: frame.metadata.radar,
            date: frame.metadata.date,
            pulse: frame.metadata.pulse,
            time: frame.metadata.time,
            quantity: frame.metadata.quantity,
            dataset: frame.metadata.dataset,
            latitude: frame.metadata.latitude,
            longitude: frame.metadata.longitude,
            elevationDeg: frame.metadata.elevationDeg,
            rows: frame.rows,
            columns: frame.columns,
            validGateCount: frame.valid.filter { $0 }.count,
            dataFingerprint: frame.dataFingerprint,
            bounds: [bounds.west, bounds.south, bounds.east, bounds.north]
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(metadata).write(to: metadataURL, options: .atomic)

        let tiffURL = directory.appendingPathComponent(stem + ".screen-view.tif")
        try writeGeoTIFF(cgImage: cgImage, bounds: bounds, to: tiffURL)

        let kmzURL = directory.appendingPathComponent(stem + ".kmz")
        let kml = kmlDocument(frame: frame, bounds: bounds)
        try StoredZIP.write(
            entries: [
                (name: "doc.kml", data: Data(kml.utf8)),
                (name: "radar.png", data: try Data(contentsOf: pngURL)),
                (name: "metadata.json", data: try Data(contentsOf: metadataURL)),
            ],
            to: kmzURL
        )

        return [
            ExportedArtifact(label: "Metadata", url: metadataURL),
            ExportedArtifact(label: "KMZ", url: kmzURL),
            ExportedArtifact(label: "GeoTIFF", url: tiffURL),
        ]
    }

    private static func geographicBounds(frame: PPIFrame) -> Bounds {
        let rangeM = max(frame.metadata.maxRangeM, 1)
        let latitudeRadians = frame.metadata.latitude * .pi / 180
        let latitudeDelta = rangeM / 111_320
        let longitudeDelta = rangeM / max(111_320 * cos(latitudeRadians), 1)
        return Bounds(
            west: frame.metadata.longitude - longitudeDelta,
            south: frame.metadata.latitude - latitudeDelta,
            east: frame.metadata.longitude + longitudeDelta,
            north: frame.metadata.latitude + latitudeDelta
        )
    }

    private static func kmlDocument(frame: PPIFrame, bounds: Bounds) -> String {
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <GroundOverlay>
            <name>\(xmlEscaped(frame.metadata.radar)) \(xmlEscaped(frame.metadata.date)) \(xmlEscaped(frame.metadata.quantity))</name>
            <Icon><href>radar.png</href></Icon>
            <LatLonBox>
              <north>\(bounds.north)</north><south>\(bounds.south)</south>
              <east>\(bounds.east)</east><west>\(bounds.west)</west>
            </LatLonBox>
          </GroundOverlay>
        </kml>
        """
    }

    private static func xmlEscaped(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func writeGeoTIFF(cgImage: CGImage, bounds: Bounds, to url: URL) throws {
        let width = cgImage.width
        let height = cgImage.height
        let bytesPerRow = width * 4
        var pixels = Data(count: bytesPerRow * height)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let drewImage = pixels.withUnsafeMutableBytes { rawBuffer -> Bool in
            guard let base = rawBuffer.baseAddress,
                  let context = CGContext(
                    data: base,
                    width: width,
                    height: height,
                    bitsPerComponent: 8,
                    bytesPerRow: bytesPerRow,
                    space: colorSpace,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                  ) else { return false }
            context.translateBy(x: 0, y: CGFloat(height))
            context.scaleBy(x: 1, y: -1)
            context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drewImage else { throw WorkspaceDocumentError.noSelection }

        let bitsPerSample: [UInt16] = [8, 8, 8, 8]
        let pixelScale = [
            (bounds.east - bounds.west) / Double(width),
            (bounds.north - bounds.south) / Double(height),
            0,
        ]
        let tiepoint: [Double] = [0, 0, 0, bounds.west, bounds.north, 0]
        let geoKeys: [UInt16] = [
            1, 1, 0, 3,
            1024, 0, 1, 2,
            1025, 0, 1, 1,
            2048, 0, 1, 4326,
        ]

        let entryCount = 14
        var externalOffset = UInt32(8 + 2 + entryCount * 12 + 4)
        let bitsOffset = externalOffset
        externalOffset += UInt32(bitsPerSample.count * 2)
        let scaleOffset = externalOffset
        externalOffset += UInt32(pixelScale.count * 8)
        let tieOffset = externalOffset
        externalOffset += UInt32(tiepoint.count * 8)
        let keysOffset = externalOffset
        externalOffset += UInt32(geoKeys.count * 2)
        let pixelOffset = externalOffset

        var data = Data()
        data.append(contentsOf: [0x49, 0x49])
        data.appendLE(UInt16(42))
        data.appendLE(UInt32(8))
        data.appendLE(UInt16(entryCount))
        appendIFD(&data, tag: 256, type: 4, count: 1, value: UInt32(width))
        appendIFD(&data, tag: 257, type: 4, count: 1, value: UInt32(height))
        appendIFD(&data, tag: 258, type: 3, count: 4, value: bitsOffset)
        appendIFD(&data, tag: 259, type: 3, count: 1, value: 1)
        appendIFD(&data, tag: 262, type: 3, count: 1, value: 2)
        appendIFD(&data, tag: 273, type: 4, count: 1, value: pixelOffset)
        appendIFD(&data, tag: 277, type: 3, count: 1, value: 4)
        appendIFD(&data, tag: 278, type: 4, count: 1, value: UInt32(height))
        appendIFD(&data, tag: 279, type: 4, count: 1, value: UInt32(pixels.count))
        appendIFD(&data, tag: 284, type: 3, count: 1, value: 1)
        appendIFD(&data, tag: 338, type: 3, count: 1, value: 2)
        appendIFD(&data, tag: 33550, type: 12, count: 3, value: scaleOffset)
        appendIFD(&data, tag: 33922, type: 12, count: 6, value: tieOffset)
        appendIFD(&data, tag: 34735, type: 3, count: UInt32(geoKeys.count), value: keysOffset)
        data.appendLE(UInt32(0))
        bitsPerSample.forEach { data.appendLE($0) }
        pixelScale.forEach { data.appendLE($0) }
        tiepoint.forEach { data.appendLE($0) }
        geoKeys.forEach { data.appendLE($0) }
        data.append(pixels)
        try data.write(to: url, options: .atomic)
    }

    private static func appendIFD(_ data: inout Data, tag: UInt16, type: UInt16, count: UInt32, value: UInt32) {
        data.appendLE(tag)
        data.appendLE(type)
        data.appendLE(count)
        data.appendLE(value)
    }
}

private enum StoredZIP {
    private struct Record {
        var name: Data
        var crc: UInt32
        var size: UInt32
        var offset: UInt32
    }

    static func write(entries: [(name: String, data: Data)], to url: URL) throws {
        var output = Data()
        var records = [Record]()
        for entry in entries {
            let name = Data(entry.name.utf8)
            let crc = crc32(entry.data)
            let offset = UInt32(output.count)
            output.appendLE(UInt32(0x04034b50))
            output.appendLE(UInt16(20))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(crc)
            output.appendLE(UInt32(entry.data.count))
            output.appendLE(UInt32(entry.data.count))
            output.appendLE(UInt16(name.count))
            output.appendLE(UInt16(0))
            output.append(name)
            output.append(entry.data)
            records.append(Record(name: name, crc: crc, size: UInt32(entry.data.count), offset: offset))
        }

        let centralOffset = UInt32(output.count)
        for record in records {
            output.appendLE(UInt32(0x02014b50))
            output.appendLE(UInt16(20))
            output.appendLE(UInt16(20))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(record.crc)
            output.appendLE(record.size)
            output.appendLE(record.size)
            output.appendLE(UInt16(record.name.count))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt16(0))
            output.appendLE(UInt32(0))
            output.appendLE(record.offset)
            output.append(record.name)
        }
        let centralSize = UInt32(output.count) - centralOffset
        output.appendLE(UInt32(0x06054b50))
        output.appendLE(UInt16(0))
        output.appendLE(UInt16(0))
        output.appendLE(UInt16(records.count))
        output.appendLE(UInt16(records.count))
        output.appendLE(centralSize)
        output.appendLE(centralOffset)
        output.appendLE(UInt16(0))
        try output.write(to: url, options: .atomic)
    }

    private static func crc32(_ data: Data) -> UInt32 {
        var crc = UInt32.max
        for byte in data {
            var value = (crc ^ UInt32(byte)) & 0xff
            for _ in 0..<8 {
                value = (value & 1) == 1 ? (value >> 1) ^ 0xedb88320 : value >> 1
            }
            crc = (crc >> 8) ^ value
        }
        return crc ^ UInt32.max
    }
}

private extension Data {
    mutating func appendLE<T: FixedWidthInteger>(_ value: T) {
        var littleEndian = value.littleEndian
        Swift.withUnsafeBytes(of: &littleEndian) { append(contentsOf: $0) }
    }

    mutating func appendLE(_ value: Double) {
        appendLE(value.bitPattern)
    }
}
