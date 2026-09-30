import Foundation
import KYVONKit

#if canImport(SwiftUI)
import SwiftUI
#endif

#if canImport(CoreLocation)
import CoreLocation

/// Shares the device location with KYVON (only while the app is in use), so weather and the
/// time zone are right. Asking is the app's job; the permission dialog is Apple's.
public final class LocationProvider: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer  // city-level is all KYVON needs
    }

    public func request() {
        #if os(iOS)
        manager.requestWhenInUseAuthorization()
        #endif
        manager.requestLocation()
    }

    public func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let coordinate = locations.last?.coordinate else { return }
        Task {
            try? await client.shareLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            try? await client.setTimezone(TimeZone.current.identifier)
        }
    }

    public func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}

    public func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        default: break
        }
    }
}
#endif

#if canImport(AVFoundation) && canImport(SwiftUI)
import AVFoundation

/// Push-to-record dictation: records a short audio file, sends it to the server for
/// transcription and hands back the text. Nothing is recognised on the device.
@MainActor
public final class VoiceController: NSObject, ObservableObject {
    @Published public private(set) var isRecording = false
    private var recorder: AVAudioRecorder?
    private var fileURL: URL?

    public func toggle(client: APIClient?, onText: @escaping (String) -> Void) {
        if isRecording {
            finish(client: client, onText: onText)
        } else {
            start()
        }
    }

    private func start() {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        session.requestRecordPermission { [weak self] granted in
            Task { @MainActor in
                guard granted, let self else { return }
                try? session.setCategory(.playAndRecord, mode: .default)
                try? session.setActive(true)
                self.beginRecording()
            }
        }
        #else
        beginRecording()
        #endif
    }

    private func beginRecording() {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kyvon-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 32_000,
        ]
        guard let recorder = try? AVAudioRecorder(url: url, settings: settings), recorder.record(forDuration: 60) else { return }
        self.recorder = recorder
        fileURL = url
        isRecording = true
    }

    private func finish(client: APIClient?, onText: @escaping (String) -> Void) {
        recorder?.stop()
        recorder = nil
        isRecording = false
        guard let url = fileURL, let client, let data = try? Data(contentsOf: url) else { return }
        try? FileManager.default.removeItem(at: url)  // the recording is not kept on the device
        Task {
            if let text = try? await client.transcribe(audio: data, filename: "voice.m4a", mimeType: "audio/mp4") {
                onText(text)
            }
        }
    }
}
#endif

#if os(iOS) && canImport(UIKit)
import UIKit

/// Registers for remote notifications and forwards the APNs token to the server.
/// The AppDelegate in the app target calls `didRegister(deviceToken:)`.
public enum PushRegistrar {
    public static func register() {
        UIApplication.shared.registerForRemoteNotifications()
    }

    public static func hex(_ token: Data) -> String { token.map { String(format: "%02x", $0) }.joined() }

    public static func didRegister(deviceToken: Data, client: APIClient?) {
        guard let client else { return }
        Task { try? await client.registerPushToken(hex(deviceToken)) }
    }
}
#endif

#if !(canImport(AVFoundation) && canImport(SwiftUI))
#if canImport(SwiftUI)
@MainActor
public final class VoiceController: ObservableObject {
    @Published public private(set) var isRecording = false
    public init() {}
    public func toggle(client: APIClient?, onText: @escaping (String) -> Void) {}
}
#endif
#endif
