import Foundation

enum ServerSettings {
    static var defaultURLString: String {
        Bundle.main.object(forInfoDictionaryKey: "UKWSRDefaultServerURL") as? String ?? "http://130.246.214.121"
    }

    static var defaultURL: URL {
        normalizedURL(from: defaultURLString) ?? URL(string: "http://130.246.214.121")!
    }

    static func normalizedURLString(from value: String) -> String? {
        normalizedURL(from: value)?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    static func normalizedURL(from value: String) -> URL? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return nil
        }

        let candidate = trimmed.contains("://") ? trimmed : "http://\(trimmed)"
        guard var components = URLComponents(string: candidate),
              let scheme = components.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              components.host?.isEmpty == false else {
            return nil
        }

        components.scheme = scheme
        if components.path == "/" {
            components.path = ""
        }
        return components.url
    }
}
