import KYVONKit

#if canImport(SwiftUI)
import SwiftUI

struct ChatTab: View {
    @ObservedObject var model: AppModel
    @State private var showConversations = false

    var body: some View {
        NavigationStack {
            ChatView(model: model)
                .background(Theme.background.ignoresSafeArea())
                .navigationTitle("KYVON")
                .inlineNavigationTitle()
                .toolbar {
                    ToolbarItem(placement: .navigation) {
                        Button { showConversations = true } label: { Label("Chats", systemImage: "list.bullet") }
                    }
                    ToolbarItem(placement: .primaryAction) {
                        Button { model.newConversation() } label: { Label("New chat", systemImage: "square.and.pencil") }
                    }
                }
                .sheet(isPresented: $showConversations) {
                    ConversationsView(model: model, isPresented: $showConversations)
                }
        }
    }
}

struct ConversationsView: View {
    @ObservedObject var model: AppModel
    @Binding var isPresented: Bool

    var body: some View {
        NavigationStack {
            Group {
                if model.conversations.isEmpty {
                    EmptyState(symbol: "message", title: "Start your first chat",
                               message: "Ask KYVON anything. Your chats are saved here.")
                } else {
                    List {
                        ForEach(model.conversations) { conversation in
                            Button {
                                Task { await model.open(conversation); isPresented = false }
                            } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(conversation.title).font(.headline)
                                    Text("\(conversation.messageCount ?? 0) messages")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .swipeActions {
                                Button("Delete", role: .destructive) { Task { await model.delete(conversation) } }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Chats")
            .toolbar { ToolbarItem { Button("Done") { isPresented = false } } }
            .refreshable { await model.refreshConversations() }
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
                        if model.messages.isEmpty {
                            EmptyState(symbol: "sparkles", title: "How can I help?",
                                       message: "Ask a question, add a task, or say \"remember ...\".")
                        }
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
            if !model.statusText.isEmpty {
                Label(model.statusText, systemImage: "gearshape")
                    .font(.caption).foregroundStyle(.secondary).padding(.horizontal)
            }
            if let error = model.errorText { ErrorBanner(text: error) }
            composer
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Message KYVON", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Theme.card)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .accessibilityLabel("Message to KYVON")
                .onSubmit(send)
            Button { voice.toggle(client: model.client) { draft = $0 } } label: {
                Image(systemName: voice.isRecording ? "stop.circle.fill" : "mic").font(.title3)
            }
            .accessibilityLabel(voice.isRecording ? "Stop recording" : "Dictate a message")
            if model.isReplying {
                Button(action: model.stopReplying) { Image(systemName: "stop.fill").font(.title3) }
                    .accessibilityLabel("Stop replying")
            } else {
                Button(action: send) { Image(systemName: "arrow.up.circle.fill").font(.title2) }
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel("Send")
            }
        }
        .padding()
    }

    private func send() {
        model.send(draft)
        draft = ""
    }
}

struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        let isUser = message.role == "user"
        VStack(alignment: isUser ? .trailing : .leading, spacing: 2) {
            Text(isUser ? "You" : "KYVON").font(.caption).foregroundStyle(.secondary)
            Text(message.content.isEmpty && message.status == "partial" ? "…" : message.content)
                .textSelection(.enabled)
                .padding(10)
                .background(isUser ? Theme.userBubble : Theme.assistantBubble)
                .clipShape(RoundedRectangle(cornerRadius: Theme.corner))
                .foregroundStyle(message.status == "error" ? Theme.danger : Color.primary)
            if message.status == "partial" && !message.content.isEmpty {
                Text("Interrupted").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
        .accessibilityElement(children: .combine)
    }
}

/// An action KYVON wants to take. It only happens if the user approves it here.
struct ApprovalCard: View {
    let run: ToolRun
    let respond: (Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Approval needed", systemImage: "hand.raised").font(.headline).foregroundStyle(Theme.warning)
            Text(run.summary)
            HStack {
                Button("Approve") { respond(true) }.buttonStyle(.borderedProminent)
                Button("Decline", role: .destructive) { respond(false) }.buttonStyle(.bordered)
            }
        }
        .padding()
        .overlay(RoundedRectangle(cornerRadius: Theme.corner).stroke(Theme.warning.opacity(0.7)))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Approval needed: \(run.summary)")
    }
}
#endif
