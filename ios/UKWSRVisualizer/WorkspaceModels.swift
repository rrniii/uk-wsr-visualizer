import Foundation
import SwiftUI

struct ComparisonLinks: Codable, Equatable {
    var view = true
    var time = true
    var variable = false
    var elevation = false

    init() {}

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        view = try values.decodeIfPresent(Bool.self, forKey: .view) ?? true
        time = try values.decodeIfPresent(Bool.self, forKey: .time) ?? true
        variable = try values.decodeIfPresent(Bool.self, forKey: .variable) ?? false
        elevation = try values.decodeIfPresent(Bool.self, forKey: .elevation) ?? false
    }
}

struct PointerFieldPreferences: Codable, Equatable {
    var value = true
    var rawValue = true
    var range = true
    var azimuth = true
    var beamHeight = true
    var elevation = true
    var coordinates = true
    var gateIndices = true

    init() {}

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        value = try values.decodeIfPresent(Bool.self, forKey: .value) ?? true
        rawValue = try values.decodeIfPresent(Bool.self, forKey: .rawValue) ?? true
        range = try values.decodeIfPresent(Bool.self, forKey: .range) ?? true
        azimuth = try values.decodeIfPresent(Bool.self, forKey: .azimuth) ?? true
        beamHeight = try values.decodeIfPresent(Bool.self, forKey: .beamHeight) ?? true
        elevation = try values.decodeIfPresent(Bool.self, forKey: .elevation) ?? true
        coordinates = try values.decodeIfPresent(Bool.self, forKey: .coordinates) ?? true
        gateIndices = try values.decodeIfPresent(Bool.self, forKey: .gateIndices) ?? true
    }
}

struct ProjectPanelSelection: Codable, Equatable, Identifiable {
    var id = UUID()
    var itemKey = ""
    var radar = ""
    var date = ""
    var pulse = ""
    var time = ""
    var quantity = ""
    var dataset = ""

    enum CodingKeys: String, CodingKey {
        case itemKey, radar, date, pulse, time, quantity, dataset
    }
}

struct ProjectFilterState: Codable, Equatable {
    var minRangeKm: Double?
    var maxRangeKm: Double?
    var minAzimuthDeg: Double?
    var maxAzimuthDeg: Double?
    var minValue: Double?
    var maxValue: Double?
    var cappiHeightM: Double?
    var noiseFloorEnabled = true
    var noiseFloorMethod = "estimated"
    var noiseFloorMarginDb = 0.0
    var noiseFloorOperation = "mask"
    var noiseFloorPercentile = 10.0
    var noiseFloorWindowBins = 11
    var textureCleanupEnabled = false
    var companionQcEnabled = false
    var backgroundModelEnabled = false

    enum CodingKeys: String, CodingKey {
        case minRangeKm = "min_range_km"
        case maxRangeKm = "max_range_km"
        case minAzimuthDeg = "min_azimuth_deg"
        case maxAzimuthDeg = "max_azimuth_deg"
        case minValue = "min_value"
        case maxValue = "max_value"
        case cappiHeightM = "cappi_height_m"
        case noiseFloorEnabled = "noise_floor_enabled"
        case noiseFloorMethod = "noise_floor_method"
        case noiseFloorMarginDb = "noise_floor_margin_db"
        case noiseFloorOperation = "noise_floor_operation"
        case noiseFloorPercentile = "noise_floor_percentile"
        case noiseFloorWindowBins = "noise_floor_window_bins"
        case textureCleanupEnabled = "texture_cleanup_enabled"
        case companionQcEnabled = "companion_qc_enabled"
        case backgroundModelEnabled = "background_model_enabled"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        minRangeKm = try values.decodeIfPresent(Double.self, forKey: .minRangeKm)
        maxRangeKm = try values.decodeIfPresent(Double.self, forKey: .maxRangeKm)
        minAzimuthDeg = try values.decodeIfPresent(Double.self, forKey: .minAzimuthDeg)
        maxAzimuthDeg = try values.decodeIfPresent(Double.self, forKey: .maxAzimuthDeg)
        minValue = try values.decodeIfPresent(Double.self, forKey: .minValue)
        maxValue = try values.decodeIfPresent(Double.self, forKey: .maxValue)
        cappiHeightM = try values.decodeIfPresent(Double.self, forKey: .cappiHeightM)
        noiseFloorEnabled = try values.decodeIfPresent(Bool.self, forKey: .noiseFloorEnabled) ?? true
        noiseFloorMethod = try values.decodeIfPresent(String.self, forKey: .noiseFloorMethod) ?? "estimated"
        noiseFloorMarginDb = try values.decodeIfPresent(Double.self, forKey: .noiseFloorMarginDb) ?? 0
        noiseFloorOperation = try values.decodeIfPresent(String.self, forKey: .noiseFloorOperation) ?? "mask"
        noiseFloorPercentile = try values.decodeIfPresent(Double.self, forKey: .noiseFloorPercentile) ?? 10
        noiseFloorWindowBins = try values.decodeIfPresent(Int.self, forKey: .noiseFloorWindowBins) ?? 11
        textureCleanupEnabled = try values.decodeIfPresent(Bool.self, forKey: .textureCleanupEnabled) ?? false
        companionQcEnabled = try values.decodeIfPresent(Bool.self, forKey: .companionQcEnabled) ?? false
        backgroundModelEnabled = try values.decodeIfPresent(Bool.self, forKey: .backgroundModelEnabled) ?? false
    }

    init(filters: RadarFilterSet) {
        minRangeKm = filters.minRangeKm
        maxRangeKm = filters.maxRangeKm
        minAzimuthDeg = filters.minAzimuthDeg
        maxAzimuthDeg = filters.maxAzimuthDeg
        minValue = filters.minValue
        maxValue = filters.maxValue
        cappiHeightM = filters.cappiHeightM
        noiseFloorEnabled = filters.noiseFloorEnabled
        noiseFloorMethod = filters.noiseFloorMethod
        noiseFloorMarginDb = filters.noiseFloorMarginDb
        noiseFloorOperation = filters.noiseFloorOperation
        noiseFloorPercentile = filters.noiseFloorPercentile
        noiseFloorWindowBins = filters.noiseFloorWindowBins
        textureCleanupEnabled = filters.textureCleanupEnabled
        companionQcEnabled = filters.companionQcEnabled
        backgroundModelEnabled = filters.backgroundModelEnabled
    }

    func applying(to filters: RadarFilterSet) -> RadarFilterSet {
        var result = filters
        result.minRangeKm = minRangeKm
        result.maxRangeKm = maxRangeKm
        result.minAzimuthDeg = minAzimuthDeg
        result.maxAzimuthDeg = maxAzimuthDeg
        result.minValue = minValue
        result.maxValue = maxValue
        result.cappiHeightM = cappiHeightM
        result.noiseFloorEnabled = noiseFloorEnabled
        result.noiseFloorMethod = noiseFloorMethod
        result.noiseFloorMarginDb = noiseFloorMarginDb
        result.noiseFloorOperation = noiseFloorOperation
        result.noiseFloorPercentile = noiseFloorPercentile
        result.noiseFloorWindowBins = noiseFloorWindowBins
        // qc-v3 starts old projects in the preservation-first safe mode.
        // Legacy broad texture/companion/background switches are not carried
        // into deletion until a signed validated model bundle is installed.
        result.textureCleanupEnabled = false
        result.companionQcEnabled = false
        result.backgroundModelEnabled = false
        result.qcRuntimeMode = .safe
        result.qcValidatedBundleID = nil
        result.experimentalLongRangeNoiseEnabled = false
        return result
    }
}

struct ProjectDisplayRange: Codable, Equatable {
    var min: Double?
    var max: Double?

    init(min: Double? = nil, max: Double? = nil) {
        self.min = min
        self.max = max
    }
}

struct ViewerProjectState: Codable, Equatable {
    var radar = ""
    var start = ""
    var end = ""
    var pulse = ""
    var time = ""
    var quantity = ""
    var dataset = ""
    var opacity = 0.88
    var palette = "auto"
    var basemap = "muted"
    var filters: ProjectFilterState
    var displayRange: ProjectDisplayRange
    var panelCount = 1
    var panelSelections: [ProjectPanelSelection] = []
    var pointerFields = PointerFieldPreferences()
    var comparisonLinks = ComparisonLinks()

    enum CodingKeys: String, CodingKey {
        case radar, start, end, pulse, time, quantity, dataset, opacity, palette, basemap, filters
        case displayRange, panelCount, panelSelections, pointerFields, comparisonLinks
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        radar = try values.decodeIfPresent(String.self, forKey: .radar) ?? ""
        start = try values.decodeIfPresent(String.self, forKey: .start) ?? ""
        end = try values.decodeIfPresent(String.self, forKey: .end) ?? start
        pulse = try values.decodeIfPresent(String.self, forKey: .pulse) ?? ""
        time = try values.decodeIfPresent(String.self, forKey: .time) ?? ""
        quantity = try values.decodeIfPresent(String.self, forKey: .quantity) ?? ""
        dataset = try values.decodeIfPresent(String.self, forKey: .dataset) ?? ""
        opacity = try values.decodeIfPresent(Double.self, forKey: .opacity) ?? 0.88
        palette = try values.decodeIfPresent(String.self, forKey: .palette) ?? "auto"
        basemap = try values.decodeIfPresent(String.self, forKey: .basemap) ?? "muted"
        filters = try values.decodeIfPresent(ProjectFilterState.self, forKey: .filters) ?? ProjectFilterState()
        displayRange = try values.decodeIfPresent(ProjectDisplayRange.self, forKey: .displayRange) ?? ProjectDisplayRange()
        panelCount = try values.decodeIfPresent(Int.self, forKey: .panelCount) ?? 1
        panelSelections = try values.decodeIfPresent([ProjectPanelSelection].self, forKey: .panelSelections) ?? []
        pointerFields = try values.decodeIfPresent(PointerFieldPreferences.self, forKey: .pointerFields) ?? PointerFieldPreferences()
        comparisonLinks = try values.decodeIfPresent(ComparisonLinks.self, forKey: .comparisonLinks) ?? ComparisonLinks()
    }

    @MainActor
    init(model: VisualizerViewModel, panelCount: Int = 1, panelSelections: [ProjectPanelSelection] = [], comparisonLinks: ComparisonLinks = .init()) {
        radar = model.selectedItem?.radar ?? ""
        start = model.selectedItem?.date ?? ""
        end = model.selectedItem?.date ?? ""
        pulse = model.selectedPulse
        time = model.selectedTime
        quantity = model.selectedQuantity
        dataset = model.selectedDataset
        opacity = model.filters.opacity
        palette = model.filters.palette
        basemap = model.mapSettings.style.rawValue
        filters = ProjectFilterState(filters: model.filters)
        displayRange = ProjectDisplayRange(min: model.filters.displayMin, max: model.filters.displayMax)
        self.panelCount = panelCount
        self.panelSelections = panelSelections
        self.comparisonLinks = comparisonLinks
        pointerFields = model.pointerFields
    }
}

struct ViewerProjectSession: Codable, Equatable, Identifiable {
    var sessionID: String
    var title: String
    var version = 1
    var createdAt: String
    var updatedAt: String
    var notes: [String] = []
    var state: ViewerProjectState

    var id: String { sessionID }

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case title, version
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case notes, state
    }
}

struct ViewerProjectDocument: Codable, Equatable, Identifiable {
    var type = "uk-wsr-visualizer-project"
    var version = 1
    var exportedAt: String
    var application = "uk-wsr-visualizer"
    var session: ViewerProjectSession

    var id: String { session.sessionID }

    enum CodingKeys: String, CodingKey {
        case type, version
        case exportedAt = "exported_at"
        case application, session
    }

    @MainActor
    static func make(title: String, model: VisualizerViewModel, comparisonLinks: ComparisonLinks = .init()) -> ViewerProjectDocument {
        let now = ISO8601DateFormatter().string(from: Date())
        let safeID = title.lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return ViewerProjectDocument(
            exportedAt: now,
            session: ViewerProjectSession(
                sessionID: safeID.isEmpty ? "project" : safeID,
                title: title,
                createdAt: now,
                updatedAt: now,
                state: ViewerProjectState(model: model, comparisonLinks: comparisonLinks)
            )
        )
    }

    func validated() throws -> ViewerProjectDocument {
        guard type == "uk-wsr-visualizer-project", version == 1, !session.sessionID.isEmpty else {
            throw WorkspaceDocumentError.invalidProject
        }
        return self
    }
}

enum WorkspaceDocumentError: LocalizedError {
    case invalidProject
    case noSelection

    var errorDescription: String? {
        switch self {
        case .invalidProject: return "Not a supported UK WSR Visualizer project file."
        case .noSelection: return "Select and render a radar scan first."
        }
    }
}

struct CitationPayload: Codable, Equatable {
    struct Software: Codable, Equatable {
        var name = "UK WSR Visualizer"
        var package = "uk-wsr-visualizer"
        var version = "0.2.1"
        var doi = "pending: mint a versioned software DOI with Zenodo"
        var repository = "https://github.com/rrniii/uk-wsr-visualizer"
    }
    struct Article: Codable, Equatable {
        var title = "UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data"
        var journal = "Weather"
        var doi = "pending: add the Weather article DOI after publication"
    }
    struct SourceData: Codable, Equatable {
        var citation = "Formal UK WSR aggregate HDF5 source-data citation pending. Do not substitute a citation for a different data product family, and do not cite the object-store mirror as the source-data record."
        var licence = "Licence and access terms pending confirmation for the released UK WSR aggregate HDF5 source objects."
    }
    struct Infrastructure: Codable, Equatable {
        var jasminAcknowledgement = "This work used JASMIN, the UK's collaborative data analysis environment."
        enum CodingKeys: String, CodingKey { case jasminAcknowledgement = "jasmin_acknowledgement" }
    }

    var software = Software()
    var article = Article()
    var sourceData = SourceData()
    var infrastructure = Infrastructure()
    var userInstruction = "If UK WSR Visualizer is used to produce a figure, export, derived object, case selection, or research result, cite the software release, the Weather article, the formal source-data record, and acknowledge JASMIN where applicable."

    enum CodingKeys: String, CodingKey {
        case software, article
        case sourceData = "source_data"
        case infrastructure
        case userInstruction = "user_instruction"
    }
}

struct ArtifactManifest: Codable, Equatable {
    struct Source: Codable, Equatable {
        var itemID: String
        var objectKey: String
        var objectURL: String
        enum CodingKeys: String, CodingKey {
            case itemID = "item_id"
            case objectKey = "object_key"
            case objectURL = "object_url"
        }
    }

    var version = 2
    var generatedAt: String
    var format: String
    var coordinateMode: String
    var selection: ViewerProjectState
    var source: Source
    var software = CitationPayload.Software()
    var article = CitationPayload.Article()
    var sourceData = CitationPayload.SourceData()
    var infrastructure = CitationPayload.Infrastructure()
    var citationInstruction = CitationPayload().userInstruction

    enum CodingKeys: String, CodingKey {
        case version
        case generatedAt = "generated_at"
        case format
        case coordinateMode = "coordinate_mode"
        case selection, source, software, article
        case sourceData = "source_data"
        case infrastructure
        case citationInstruction = "citation_instruction"
    }

    @MainActor
    static func make(format: String, coordinateMode: String, model: VisualizerViewModel) throws -> ArtifactManifest {
        guard let item = model.selectedItem else { throw WorkspaceDocumentError.noSelection }
        return ArtifactManifest(
            generatedAt: ISO8601DateFormatter().string(from: Date()),
            format: format,
            coordinateMode: coordinateMode,
            selection: ViewerProjectState(model: model),
            source: Source(itemID: item.id, objectKey: item.objectKey, objectURL: model.selectedSourceURLString)
        )
    }
}

@MainActor
final class WorkspaceProjectStore: ObservableObject {
    @Published private(set) var projects: [ViewerProjectDocument] = []
    @Published var statusMessage = ""

    private let directory: URL
    private let encoder: JSONEncoder
    private let decoder = JSONDecoder()

    init(directory: URL? = nil) {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        self.directory = directory ?? documents.appendingPathComponent("Projects", isDirectory: true)
        encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        reload()
    }

    func reload() {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let urls = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
        projects = urls.filter { $0.pathExtension == "json" }.compactMap { url in
            guard let data = try? Data(contentsOf: url), let project = try? decoder.decode(ViewerProjectDocument.self, from: data) else { return nil }
            return try? project.validated()
        }.sorted { $0.session.updatedAt > $1.session.updatedAt }
    }

    @discardableResult
    func save(_ project: ViewerProjectDocument) throws -> URL {
        let valid = try project.validated()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = fileURL(for: valid)
        try encoder.encode(valid).write(to: url, options: .atomic)
        reload()
        statusMessage = "Saved \(valid.session.title)."
        return url
    }

    func importProject(from url: URL) throws -> ViewerProjectDocument {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        let project = try decoder.decode(ViewerProjectDocument.self, from: Data(contentsOf: url)).validated()
        try save(project)
        statusMessage = "Imported \(project.session.title)."
        return project
    }

    func delete(_ project: ViewerProjectDocument) throws {
        try FileManager.default.removeItem(at: fileURL(for: project))
        reload()
    }

    func fileURL(for project: ViewerProjectDocument) -> URL {
        directory.appendingPathComponent(project.session.sessionID).appendingPathExtension("uk-wsr-visualizer-project.json")
    }
}

enum WorkspaceJSONExporter {
    static func writeManifest(_ manifest: ArtifactManifest) throws -> URL {
        try write(manifest, filename: "\(fileStem(manifest.selection))-\(manifest.format).manifest.json")
    }

    static func writeCitation() throws -> URL {
        try write(CitationPayload(), filename: "uk-wsr-visualizer-citation.json")
    }

    private static func write<T: Encodable>(_ value: T, filename: String) throws -> URL {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let directory = documents.appendingPathComponent("Downloads", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent(filename)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(value).write(to: url, options: .atomic)
        return url
    }

    private static func fileStem(_ state: ViewerProjectState) -> String {
        [state.radar, state.start, state.pulse, state.time, state.quantity, state.dataset]
            .filter { !$0.isEmpty }
            .joined(separator: "-")
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
    }
}

@MainActor
final class PlaybackController: ObservableObject {
    @Published private(set) var isPlaying = false
    @Published var interval = 0.8
    private var task: Task<Void, Never>?

    func toggle(model: VisualizerViewModel) {
        isPlaying ? stop() : play(model: model)
    }

    func play(model: VisualizerViewModel) {
        guard model.canStepTime else { return }
        stop()
        isPlaying = true
        task = Task { [weak self, weak model] in
            while !Task.isCancelled {
                let delay = UInt64(max(self?.interval ?? 0.8, 0.2) * 1_000_000_000)
                try? await Task.sleep(nanoseconds: delay)
                guard !Task.isCancelled, let self, let model else { return }
                model.stepTime(by: 1)
                if !self.isPlaying { return }
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
        isPlaying = false
    }

    deinit { task?.cancel() }
}
