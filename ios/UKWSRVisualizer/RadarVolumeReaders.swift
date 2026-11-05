import Foundation
import SwiftUI

protocol RadarVolumeReader {
    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord]
    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField
}

extension RadarVolumeReader {
    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        []
    }
}

struct NativeHDF5VolumeReader: RadarVolumeReader {
    private static let suppressionCompanionCandidates = [
        "DBZH",
        "CI",
        "SQIH",
        "RHOHV",
        "ZDR",
        "PHIDP", "UPHIDP",
        "VRADH",
        "WRADH",
        "LONG_RANGE_NOISE_DBC_H",
        "LONG_RANGE_NOISE_DBC_V",
    ]

    private struct DecodedPolarSource {
        var values: [Float]
        var rows: Int
        var columns: Int
        var dataset: String
        var quantity: String
        var latitude: Double
        var longitude: Double
        var heightM: Double?
        var elevationDeg: Double?
        var rstartKm: Double
        var rscaleM: Double
    }

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        if fileURL.pathExtension.lowercased() == "json" {
            return try JSONPolarFixtureReader().inspectFields(from: fileURL, item: item, pulse: pulse, time: time)
        }

        var records = [UKHDF5FieldRecord](repeating: UKHDF5FieldRecord(), count: 512)
        var recordCount: Int32 = 0
        var errorBuffer = [CChar](repeating: 0, count: 512)
        let didInspect = fileURL.withUnsafeFileSystemRepresentation { pathPointer -> Int32 in
            guard let pathPointer else { return 0 }
            return records.withUnsafeMutableBufferPointer { buffer in
                UKHDF5InspectODIMFields(
                    pathPointer,
                    buffer.baseAddress,
                    Int32(buffer.count),
                    &recordCount,
                    &errorBuffer,
                    errorBuffer.count
                )
            }
        }

        guard didInspect != 0 else {
            throw RadarAppError.hdf5ReadFailed(String(cString: errorBuffer))
        }

        return records.prefix(Int(recordCount)).map { record in
            let datasetName = fixedCString(record.datasetName)
            let dataset = datasetName.hasPrefix("dataset") ? String(datasetName.dropFirst("dataset".count)) : datasetName
            let shape = [Int(record.rows), Int(record.columns)].filter { $0 > 0 }
            return QuantityRecord(
                pulse: pulse,
                time: time,
                dataset: dataset,
                kind: "data",
                index: String(record.dataIndex),
                quantity: fixedCString(record.quantity),
                shape: shape,
                dtype: "",
                elevationDeg: record.elevationDeg.isFinite ? record.elevationDeg : nil
            )
        }
    }

    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        if fileURL.pathExtension.lowercased() == "json" {
            return try JSONPolarFixtureReader().readPolarField(from: fileURL, item: item, selection: selection)
        }

        let requestedDataset = selection.dataset ?? ""
        let decoded = try readCPolarField(from: fileURL, dataset: requestedDataset, quantity: selection.quantity)
        let decodedDataset = decoded.dataset
        let decodedQuantity = decoded.quantity.isEmpty ? selection.quantity : decoded.quantity
        let companionFields = suppressionCompanionFields(
            from: fileURL,
            dataset: decodedDataset.isEmpty ? requestedDataset : decodedDataset,
            selected: decoded
        )
        let gateSource = reflectivityGateSource(
            selected: decoded,
            selectedQuantity: decodedQuantity,
            companionFields: companionFields
        )
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: decodedQuantity,
            dataset: decodedDataset.isEmpty ? selection.dataset ?? "auto" : decodedDataset,
            latitude: decoded.latitude,
            longitude: decoded.longitude,
            heightM: decoded.heightM,
            elevationDeg: decoded.elevationDeg,
            rstartKm: decoded.rstartKm,
            rscaleM: decoded.rscaleM,
            nbins: decoded.columns,
            nrays: decoded.rows
        )

        return PolarField(
            values: decoded.values,
            gateValues: gateSource?.values,
            gateQuantity: gateSource?.quantity,
            companionFields: companionFields,
            rows: decoded.rows,
            columns: decoded.columns,
            metadata: metadata
        )
    }

    private func readCPolarField(from fileURL: URL, dataset: String, quantity: String) throws -> DecodedPolarSource {
        var cField = UKHDF5PolarField()
        var errorBuffer = [CChar](repeating: 0, count: 512)

        let didRead = fileURL.withUnsafeFileSystemRepresentation { pathPointer -> Int32 in
            guard let pathPointer else { return 0 }
            return dataset.withCString { datasetPointer in
                quantity.withCString { quantityPointer in
                    UKHDF5ReadODIMField(
                        pathPointer,
                        datasetPointer,
                        quantityPointer,
                        &cField,
                        &errorBuffer,
                        errorBuffer.count
                    )
                }
            }
        }

        guard didRead != 0 else {
            throw RadarAppError.hdf5ReadFailed(String(cString: errorBuffer))
        }

        defer { UKHDF5FreePolarField(&cField) }

        let rows = Int(cField.rows)
        let columns = Int(cField.columns)
        let valueCount = Int(cField.valueCount)
        guard rows > 0, columns > 0, valueCount == rows * columns, let valuesPointer = cField.values else {
            throw RadarAppError.hdf5ReadFailed("The decoded HDF5 field had an invalid shape.")
        }

        let values = Array(UnsafeBufferPointer(start: valuesPointer, count: valueCount))
        return DecodedPolarSource(
            values: values,
            rows: rows,
            columns: columns,
            dataset: fixedCString(cField.datasetName),
            quantity: fixedCString(cField.quantity),
            latitude: cField.latitude.isFinite ? cField.latitude : 0,
            longitude: cField.longitude.isFinite ? cField.longitude : 0,
            heightM: cField.heightM.isFinite ? cField.heightM : nil,
            elevationDeg: cField.elevationDeg.isFinite ? cField.elevationDeg : nil,
            rstartKm: cField.rstartKm.isFinite ? cField.rstartKm : 0,
            rscaleM: cField.rscaleM.isFinite ? cField.rscaleM : 1000
        )
    }

    private func suppressionCompanionFields(
        from fileURL: URL,
        dataset: String,
        selected: DecodedPolarSource
    ) -> [String: [Float]] {
        var fields = [normalizedQuantityKey(selected.quantity): selected.values]
        for quantity in Self.suppressionCompanionCandidates {
            let key = normalizedQuantityKey(quantity)
            if fields[key] != nil {
                continue
            }
            guard let source = try? readCPolarField(from: fileURL, dataset: dataset, quantity: quantity),
                  source.rows == selected.rows,
                  let values = broadcastCompanionValues(source, columns: selected.columns) else {
                continue
            }
            fields[normalizedQuantityKey(source.quantity.isEmpty ? quantity : source.quantity)] = values
        }
        return fields
    }

    private func broadcastCompanionValues(_ source: DecodedPolarSource, columns: Int) -> [Float]? {
        if source.columns == columns {
            return source.values
        }
        guard source.columns == 1, columns > 0, source.values.count == source.rows else {
            return nil
        }
        var expanded = [Float]()
        expanded.reserveCapacity(source.rows * columns)
        for value in source.values {
            expanded.append(contentsOf: repeatElement(value, count: columns))
        }
        return expanded
    }

    private func reflectivityGateSource(
        selected: DecodedPolarSource,
        selectedQuantity: String,
        companionFields: [String: [Float]]
    ) -> (values: [Float], quantity: String)? {
        if isReflectivityQuantity(selectedQuantity) {
            return (selected.values, selectedQuantity)
        }

        for quantity in ["DBZH", "TH", "DBZ", "DBZV", "DBZHC", "DBZVC", "CZ", "DZ", "AZ", "Z"] {
            if let values = companionFields[normalizedQuantityKey(quantity)] {
                return (values, quantity)
            }
        }
        return nil
    }

    private func fixedCString<T>(_ tuple: T) -> String {
        withUnsafeBytes(of: tuple) { bytes in
            guard let baseAddress = bytes.baseAddress else { return "" }
            return String(cString: baseAddress.assumingMemoryBound(to: CChar.self))
        }
    }
}

struct JSONPolarFixtureReader: RadarVolumeReader {
    private struct Fixture: Codable {
        var values: [[Double?]]
        var metadata: FixtureMetadata
    }

    private struct FixtureMetadata: Codable {
        var latitude: Double
        var longitude: Double
        var heightM: Double?
        var elevationDeg: Double?
        var rstartKm: Double
        var rscaleM: Double

        enum CodingKeys: String, CodingKey {
            case latitude
            case longitude
            case heightM = "height_m"
            case elevationDeg = "elevation_deg"
            case rstartKm = "rstart_km"
            case rscaleM = "rscale_m"
        }
    }

    func inspectFields(from fileURL: URL, item: CatalogItem, pulse: String, time: String) throws -> [QuantityRecord] {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: fileURL))
        return [QuantityRecord(
            pulse: pulse,
            time: time,
            dataset: "1",
            kind: "data",
            index: "1",
            quantity: "DBZH",
            shape: [fixture.values.count, fixture.values.first?.count ?? 0].filter { $0 > 0 },
            dtype: "float32",
            elevationDeg: fixture.metadata.elevationDeg
        )]
    }

    func readPolarField(from fileURL: URL, item: CatalogItem, selection: FieldSelection) throws -> PolarField {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: fileURL))
        let rows = fixture.values.count
        let columns = fixture.values.first?.count ?? 0
        guard rows > 0, columns > 0 else {
            throw RadarAppError.unsupportedFixture(fileURL.lastPathComponent)
        }
        let values = fixture.values.flatMap { row in
            row.map { value in value.map(Float.init) ?? Float.nan }
        }
        let metadata = RadarGridMetadata(
            radar: item.radar,
            date: item.date,
            pulse: selection.pulse,
            time: selection.time,
            quantity: selection.quantity,
            dataset: selection.dataset.map { $0.hasPrefix("dataset") ? $0 : "dataset\($0)" } ?? "auto",
            latitude: fixture.metadata.latitude,
            longitude: fixture.metadata.longitude,
            heightM: fixture.metadata.heightM,
            elevationDeg: fixture.metadata.elevationDeg,
            rstartKm: fixture.metadata.rstartKm,
            rscaleM: fixture.metadata.rscaleM,
            nbins: columns,
            nrays: rows
        )
        return PolarField(
            values: values,
            gateValues: isReflectivityQuantity(selection.quantity) ? values : nil,
            gateQuantity: isReflectivityQuantity(selection.quantity) ? selection.quantity : nil,
            companionFields: isReflectivityQuantity(selection.quantity) ? [selection.quantity: values] : [:],
            rows: rows,
            columns: columns,
            metadata: metadata
        )
    }
}
