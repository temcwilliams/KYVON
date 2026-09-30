import KYVONApp
import KYVONKit
import SwiftUI
import UIKit

/// The iPhone/iPad app entry point. Everything else lives in the KYVONApp package library.
@main
struct KYVONMain: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel(tokens: KeychainTokenStore())
    @State private var location: LocationProvider?
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
                .onAppear { AppDelegate.model = model }
                .onChange(of: scenePhase) { phase in
                    guard phase == .active, case .signedIn = model.phase, let client = model.client else { return }
                    if location == nil { location = LocationProvider(client: client) }
                    location?.request()
                    PushRegistrar.register()
                    Task { await model.refreshApprovals() }
                }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    @MainActor static weak var model: AppModel?

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in PushRegistrar.didRegister(deviceToken: deviceToken, client: Self.model?.client) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {}
}
