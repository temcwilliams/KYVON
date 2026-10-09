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
    }
}

struct ServerView: View {
    @ObservedObject var model: AppModel
    @State private var address = ""

    var body: some View {
        Form {
            Section("Your KYVON server") {
                TextField("https://kyvon.example.com", text: $address)
                    .textContentType(.URL)
                    .autocorrectionDisabled()
                Button("Continue") { Task { await model.setServer(address) } }
            }
            if let error = model.errorText { Text(error).foregroundStyle(.red) }
        }
    }
}

struct LoginView: View {
    @ObservedObject var model: AppModel
    @State private var username = ""
    @State private var password = ""

    var body: some View {
        Form {
            Section("Sign in to KYVON") {
                TextField("Username", text: $username).autocorrectionDisabled()
                SecureField("Password", text: $password)
                Button("Sign in") {
                    Task { await model.signIn(username: username, password: password, deviceName: DeviceInfo.name) }
                }
            }
            if let error = model.errorText { Text(error).foregroundStyle(.red).accessibilityLabel("Error: \(error)") }
        }
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

struct MainView: View {
    @ObservedObject var model: AppModel
    @State private var showConversations = false

    var body: some View {
        NavigationStack {
            ChatView(model: model)
                .navigationTitle("KYVON")
                .toolbar {
                    ToolbarItem(placement: .navigation) {
                        Button { showConversations = true } label: { Label("Chats", systemImage: "sidebar.left") }
                    }
                    ToolbarItem {
                        Button { model.newConversation() } label: { Label("New chat", systemImage: "square.and.pencil") }
                    }
                    ToolbarItem {
                        Button("Sign out") { Task { await model.signOut() } }
                    }
                }
                .sheet(isPresented: $showConversations) { ConversationsView(model: model, isPresented: $showConversations) }
        }
    }
}

struct ConversationsView: View {
    @ObservedObject var model: AppModel
    @Binding var isPresented: Bool

    var body: some View {
        NavigationStack {
            List {
                ForEach(model.conversations) { conversation in
                    Button {
                        Task { await model.open(conversation); isPresented = false }
                    } label: {
                        VStack(alignment: .leading) {
                            Text(conversation.title).font(.headline)
                            Text("\(conversation.messageCount ?? 0) messages").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .swipeActions { Button("Delete", role: .destructive) { Task { await model.delete(conversation) } } }
                }
            }
            .navigationTitle("Chats")
            .toolbar { ToolbarItem { Button("Done") { isPresented = false } } }
        }
    }
}

struct ChatView: View {
    @ObservedObject var model: AppModel
    @State private var draft = ""
    @StateObject private var voice = VoiceController()

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(model.messages) { message in
                            MessageRow(message: message).id(message.id)
                        }
                        ForEach(model.pendingApprovals) { run in
                            ApprovalCard(run: run) { approve in Task { await model.respond(to: run, approve: approve) } }
                        }
                    }
                    .padding()
                }
                .onChange(of: model.messages.last?.content) { _ in
                    if let last = model.messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            if !model.statusText.isEmpty { Text("⚙ \(model.statusText)").font(.caption).padding(.horizontal) }
            if let error = model.errorText { Text(error).font(.caption).foregroundStyle(.red).padding(.horizontal) }
            HStack {
                TextField("Message KYVON", text: $draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Message to KYVON")
                    .onSubmit(send)
                Button { voice.toggle(client: model.client) { draft = $0 } } label: {
                    Image(systemName: voice.isRecording ? "stop.circle.fill" : "mic")
                }
                .accessibilityLabel(voice.isRecording ? "Stop recording" : "Dictate a message")
                if model.isReplying {
                    Button("Stop", action: model.stopReplying)
                } else {
                    Button("Send", action: send).disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .padding()
        }
    }

    private func send() {
        model.send(draft)
        draft = ""
    }
}

struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        VStack(alignment: message.role == "user" ? .trailing : .leading, spacing: 2) {
            Text(message.role == "user" ? "You" : "Kyvon").font(.caption).foregroundStyle(.secondary)
            Text(message.content.isEmpty && message.status == "partial" ? "…" : message.content)
                .padding(10)
                .background(message.role == "user" ? Color.accentColor.opacity(0.25) : Color.gray.opacity(0.2))
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .foregroundStyle(message.status == "error" ? Color.red : Color.primary)
            if message.status == "partial" && !message.content.isEmpty { Text("interrupted").font(.caption2).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: message.role == "user" ? .trailing : .leading)
        .accessibilityElement(children: .combine)
    }
}

/// An action KYVON wants to take. It only happens if the user approves it here.
struct ApprovalCard: View {
    let run: ToolRun
    let respond: (Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Approval needed").font(.headline)
            Text(run.summary)
            HStack {
                Button("Approve") { respond(true) }.buttonStyle(.borderedProminent)
                Button("Decline", role: .destructive) { respond(false) }.buttonStyle(.bordered)
            }
        }
        .padding()
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.yellow.opacity(0.7)))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Approval needed: \(run.summary)")
    }
}
#endif
