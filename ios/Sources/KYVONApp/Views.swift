import KYVONKit

#if canImport(SwiftUI)
import SwiftUI

public struct RootView: View {
    @ObservedObject var model: AppModel
    public init(model: AppModel) { self.model = model }

    public var body: some View {
        Group {
            switch model.phase {
            case .needsServer: ServerView(model: model)
            case .signedOut: LoginView(model: model)
            case .signedIn: MainView(model: model)
            }
        }
        .task { await model.start() }
        .preferredColorScheme(.dark)
        .tint(Theme.accent)
    }
}

/// A centred, single-purpose form used for the first two steps (server address, then sign-in).
struct SetupScreen<Fields: View>: View {
    let title: String
    let subtitle: String
    let error: String?
    @ViewBuilder var fields: Fields

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("KYVON").font(.largeTitle.weight(.semibold))
                Text(title).font(.title3.weight(.medium))
                Text(subtitle).foregroundStyle(.secondary)
                fields
                if let error { ErrorBanner(text: error).padding(.horizontal, 0) }
            }
            .padding(24)
            .frame(maxWidth: 480, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.background.ignoresSafeArea())
    }
}

struct ServerView: View {
    @ObservedObject var model: AppModel
    @State private var address = ""

    var body: some View {
        SetupScreen(title: "Connect to your server",
                    subtitle: "Enter the address of your KYVON server. It must start with https://.",
                    error: model.errorText) {
            TextField("https://kyvon.example.com", text: $address)
                .textContentType(.URL)
                .plainTextInput(url: true)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.continue)
                .onSubmit { Task { await model.setServer(address) } }
            Button("Continue") { Task { await model.setServer(address) } }
                .buttonStyle(.borderedProminent)
        }
    }
}

struct LoginView: View {
    @ObservedObject var model: AppModel
    @State private var username = ""
    @State private var password = ""

    var body: some View {
        SetupScreen(title: "Sign in",
                    subtitle: "Your password is sent once. This device keeps only its own revocable token.",
                    error: model.errorText) {
            TextField("Username", text: $username)
                .textContentType(.username)
                .plainTextInput()
                .textFieldStyle(.roundedBorder)
            SecureField("Password", text: $password)
                .textContentType(.password)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.go)
                .onSubmit(signIn)
            Button("Sign in", action: signIn).buttonStyle(.borderedProminent)
        }
    }

    private func signIn() {
        Task { await model.signIn(username: username, password: password, deviceName: DeviceInfo.name) }
    }
}

enum DeviceInfo {
    static var name: String {
        #if os(iOS)
        return UIDevice.current.name
        #else
        return Host.current().localizedName ?? "Mac"
        #endif
    }
}

/// The five sections. Approvals appear inside Chat; unread reminders badge the Inbox.
struct MainView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        TabView {
            ChatTab(model: model)
                .tabItem { Label("Chat", systemImage: "message") }
                .badge(model.pendingApprovals.count)
            TasksView(model: model)
                .tabItem { Label("Tasks", systemImage: "checklist") }
                .badge(model.openTasks.filter(\.overdue).count)
            MemoryView(model: model)
                .tabItem { Label("Memory", systemImage: "brain") }
            InboxView(model: model)
                .tabItem { Label("Inbox", systemImage: "bell") }
                .badge(model.unreadCount)
            SettingsView(model: model)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}
#endif
