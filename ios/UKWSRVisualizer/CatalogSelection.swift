import Foundation

struct CatalogSearchCriteria: Hashable {
    var radar = ""
    var year = ""
    var pulse = ""
    var quantity = ""
    var startDate = ""
    var endDate = ""
    var text = ""
    var renderableOnly = false
    var cachedOnly = false
    var sortMode: CatalogSortMode = .newestFirst
}

enum CatalogSortMode: String, CaseIterable, Hashable, Codable {
    case newestFirst
    case radarThenNewest
    case cachedFirst

    var displayName: String {
        switch self {
        case .newestFirst:
            return "Newest first"
        case .radarThenNewest:
            return "Radar, newest"
        case .cachedFirst:
            return "Cached first"
        }
    }
}

struct SourceDiagnosticRow: Identifiable, Hashable {
    var label: String
    var value: String

    var id: String { label }
}

struct LaunchDefaultSelection: Hashable {
    var itemID: String
    var statusText: String
    var preferLatestTime = true
}

struct RecentCatalogSelection: Codable, Hashable, Identifiable {
    var itemID: String
    var radar: String
    var radarDisplayName: String
    var date: String
    var pulse: String
    var time: String
    var quantity: String
    var dataset: String
    var selectedAt: Date

    var id: String { itemID }

    var title: String {
        "\(radarDisplayName) \(CatalogItem.formattedDate(date))"
    }

    var detailText: String {
        [pulse, time, quantity]
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
    }
}

protocol RecentSelectionStoring {
    func loadRecentSelections() -> [RecentCatalogSelection]
    func saveRecentSelections(_ selections: [RecentCatalogSelection])
}

struct UserDefaultsRecentSelectionStore: RecentSelectionStoring {
    private let defaults: UserDefaults
    private let key: String

    init(
        defaults: UserDefaults = .standard,
        key: String = "UKWSRRecentCatalogSelections"
    ) {
        self.defaults = defaults
        self.key = key
    }

    func loadRecentSelections() -> [RecentCatalogSelection] {
        guard let data = defaults.data(forKey: key),
              let selections = try? JSONDecoder().decode([RecentCatalogSelection].self, from: data) else {
            return []
        }
        return selections.sorted { $0.selectedAt > $1.selectedAt }
    }

    func saveRecentSelections(_ selections: [RecentCatalogSelection]) {
        guard let data = try? JSONEncoder().encode(selections) else { return }
        defaults.set(data, forKey: key)
    }
}
