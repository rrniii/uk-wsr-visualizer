import CoreLocation
import Foundation

@MainActor
protocol DeviceLocationProviding {
    func requestCurrentLocation(timeout: TimeInterval) async -> CLLocation?
}

@MainActor
final class DeviceLocationProvider: NSObject, DeviceLocationProviding, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?
    private var timeoutTask: Task<Void, Never>?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
    }

    func requestCurrentLocation(timeout: TimeInterval = 4) async -> CLLocation? {
        guard CLLocationManager.locationServicesEnabled() else { return nil }
        if let recent = manager.location, abs(recent.timestamp.timeIntervalSinceNow) < 15 * 60 {
            return recent
        }

        return await withCheckedContinuation { continuation in
            finishExistingRequest(with: nil)
            self.continuation = continuation
            timeoutTask = Task { [weak self] in
                let nanoseconds = UInt64(max(timeout, 0.5) * 1_000_000_000)
                do {
                    try await Task.sleep(nanoseconds: nanoseconds)
                } catch {
                    return
                }
                await MainActor.run {
                    guard let self else { return }
                    self.finish(with: self.manager.location)
                }
            }

            switch manager.authorizationStatus {
            case .notDetermined:
                manager.requestWhenInUseAuthorization()
            case .authorizedAlways, .authorizedWhenInUse:
                manager.requestLocation()
            case .denied, .restricted:
                finish(with: manager.location)
            @unknown default:
                finish(with: manager.location)
            }
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            finish(with: manager.location)
        case .notDetermined:
            break
        @unknown default:
            finish(with: manager.location)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        finish(with: locations.sorted { $0.horizontalAccuracy < $1.horizontalAccuracy }.first ?? manager.location)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(with: manager.location)
    }

    private func finishExistingRequest(with location: CLLocation?) {
        guard continuation != nil else { return }
        finish(with: location)
    }

    private func finish(with location: CLLocation?) {
        timeoutTask?.cancel()
        timeoutTask = nil
        let currentContinuation = continuation
        continuation = nil
        currentContinuation?.resume(returning: location)
    }
}

@MainActor
struct StaticDeviceLocationProvider: DeviceLocationProviding {
    var location: CLLocation?

    func requestCurrentLocation(timeout: TimeInterval) async -> CLLocation? {
        location
    }
}
