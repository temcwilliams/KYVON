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
    private enum Mode { case signIn, signUp, forgot }

    @ObservedObject var model: AppModel
    @State private var mode: Mode = .signIn
    @State private var username = ""
    @State private var password = ""
    @State private var email = ""
    @State private var accepted = false

    private var canSignUp: Bool { model.publicConfig?.isHosted == true && model.publicConfig?.signupOpen == true }
    private var hosted: Bool { model.publicConfig?.isHosted == true }

    var body: some View {
        SetupScreen(title: title, subtitle: subtitle, error: model.errorText) {
            if let info = model.infoText {
                Label(info, systemImage: "checkmark.circle").font(.footnote).foregroundStyle(Theme.success)
            }
            switch mode {
            case .signIn: signInFields
            case .signUp: signUpFields
            case .forgot: forgotFields
            }
            footer
        }
    }

    private var title: String {
        switch mode {
        case .signIn: return "Sign in"
        case .signUp: return "Create your account"
        case .forgot: return "Reset your password"
        }
    }

    private var subtitle: String {
        switch mode {
        case .signIn: return "Your password is sent once. This device keeps only its own revocable token."
        case .signUp: return "We'll email you a link to confirm your address before you can start."
        case .forgot: return "Enter your email and we'll send a reset link."
        }
    }

    @ViewBuilder private var signInFields: some View {
        TextField(hosted ? "Email or username" : "Username", text: $username)
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

    @ViewBuilder private var signUpFields: some View {
        TextField("Email", text: $email)
            .emailInput()
            .textFieldStyle(.roundedBorder)
        SecureField("Password (10+ characters)", text: $password)
            .newPasswordInput()
            .textFieldStyle(.roundedBorder)
        Toggle(isOn: $accepted) {
            VStack(alignment: .leading, spacing: 4) {
                Text("I agree to the terms of use and privacy policy.").font(.footnote)
                HStack(spacing: 12) {
                    Link("Terms", destination: LegalLinks.terms)
                    Link("Privacy", destination: LegalLinks.privacy)
                }
                .font(.footnote)
            }
        }
        Button("Create account") {
            Task { await model.signUp(email: email, password: password, acceptTerms: accepted) }
        }
        .buttonStyle(.borderedProminent)
        .disabled(!accepted)
    }

    @ViewBuilder private var forgotFields: some View {
        TextField("Email", text: $email)
            .emailInput()
            .textFieldStyle(.roundedBorder)
        Button("Send reset link") { Task { await model.forgotPassword(email: email) } }
            .buttonStyle(.borderedProminent)
    }

    @ViewBuilder private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if mode != .signIn {
                Button("Back to sign in") { mode = .signIn; model.infoText = nil }
            }
            if mode == .signIn && canSignUp {
                Button("Create an account") { mode = .signUp; model.infoText = nil }
            }
            if mode == .signIn && hosted {
                Button("Forgot password?") { mode = .forgot; model.infoText = nil }
            }
            Button("Use a different server") { model.changeServer() }
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .font(.subheadline)
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
