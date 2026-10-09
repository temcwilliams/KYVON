import KYVONKit

#if canImport(SwiftUI)
import SwiftUI

public struct RootView: View {
    @ObservedObject var model: AppModel
    public init(model: AppModel) { self.model = model }

    public var body: some View {
        Group {
            switch model.phase {
            case .needsConsent: ConsentView(model: model)
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

/// Shown once before anything else: what leaves the device, and where it goes.
struct ConsentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        SetupScreen(title: "Before you start",
                    subtitle: "KYVON connects to a server that you run. Here is where your information goes.",
                    error: nil) {
            VStack(alignment: .leading, spacing: 12) {
                point("server.rack", "Your server stores it",
                      "Messages, tasks, memories, voice recordings and, if you allow it, your approximate location are sent to your own KYVON server. The developer of this app does not run that server or receive that data.")
                point("sparkles", "An AI provider reads your messages",
                      "To write replies, your server sends your messages and the context it needs to an AI provider (Groq by default). Voice recordings go to Groq to be turned into text. Check your server's settings to see which providers it uses.")
                point("hand.raised", "You approve actions",
                      "KYVON asks before it changes anything outside itself, such as a calendar event.")
            }
            Button("Agree and continue") { Task { await model.acceptConsent() } }
                .buttonStyle(.borderedProminent)
            HStack(spacing: 16) {
                Link("Privacy policy", destination: LegalLinks.privacy)
                Link("Terms of use", destination: LegalLinks.terms)
            }
            .font(.footnote)
        }
    }

    private func point(_ symbol: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol).foregroundStyle(Theme.accent).frame(width: 24).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
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
                .tabItem { Label("Memory", systemImage: Theme.memorySymbol) }
            InboxView(model: model)
                .tabItem { Label("Inbox", systemImage: "bell") }
                .badge(model.unreadCount)
            SettingsView(model: model)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}
#endif
