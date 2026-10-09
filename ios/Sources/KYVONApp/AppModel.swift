import Foundation
import KYVONKit

#if canImport(SwiftUI)
import SwiftUI

/// The state behind every screen. It only calls the KYVON API: no assistant logic lives in
/// the app, so the server stays the single source of truth.
@MainActor
public final class AppModel: ObservableObject {
    public enum Phase: Equatable { case needsServer, signedOut, signedIn(APIUser) }

    @Published public private(set) var phase: Phase = .needsServer
    @Published public var conversations: [Conversation] = []
    @Published public var messages: [ChatMessage] = []
    @Published public var pendingApprovals: [ToolRun] = []
    @Published public var openTasks: [KTask] = []
    @Published public var doneTasks: [KTask] = []
    @Published public var memories: [Memory] = []
    @Published public var notifications: [KNotification] = []
    @Published public var unreadCount = 0
    @Published public var preferences: Preferences?
    @Published public var currentConversationId: Int?
    @Published public var isReplying = false
    @Published public var statusText = ""
    @Published public var errorText: String?

    public private(set) var client: APIClient?
    private let tokens: TokenStore
    private let defaults: UserDefaults
    private var streamTask: Task<Void, Never>?

    public init(tokens: TokenStore, defaults: UserDefaults = .standard, transport: HTTPTransport = URLSessionTransport()) {
        self.tokens = tokens
        self.defaults = defaults
        self.transport = transport
    }

    private let transport: HTTPTransport

    // MARK: server and sign-in

    /// The URL is checked so a typo cannot send the password over plain HTTP to another machine.
    public static func validatedServerURL(_ text: String) -> URL? {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespaces)), let host = url.host else { return nil }
        let local = host == "localhost" || host == "127.0.0.1" || host.hasSuffix(".local")
        guard url.scheme == "https" || (url.scheme == "http" && local) else { return nil }
        return url
    }

    public func start() async {
        guard let text = defaults.string(forKey: "serverURL"), let url = Self.validatedServerURL(text) else {
            phase = .needsServer
            return
        }
        client = APIClient(baseURL: url, tokens: tokens, transport: transport)
        if client?.hasToken == true, let user = try? await client?.currentUser() {
            phase = .signedIn(user)
            await refreshAll()
        } else {
            phase = .signedOut
        }
    }

    public func setServer(_ text: String) async {
        guard let url = Self.validatedServerURL(text) else {
            errorText = "Enter your KYVON address, starting with https://"
            return
        }
        defaults.set(url.absoluteString, forKey: "serverURL")
        errorText = nil
        await start()
    }

    public func signIn(username: String, password: String, deviceName: String) async {
        guard let client else { return }
        do {
            phase = .signedIn(try await client.login(username: username, password: password, deviceName: deviceName))
            errorText = nil
            await refreshAll()
        } catch { errorText = describe(error) }
    }

    public func signOut() async {
        streamTask?.cancel()
        await client?.logout()
        conversations = []; messages = []; pendingApprovals = []; currentConversationId = nil
        openTasks = []; doneTasks = []; memories = []; notifications = []; unreadCount = 0; preferences = nil
        phase = .signedOut
    }

    // MARK: data

    public func refreshAll() async {
        await refreshConversations()
        await refreshApprovals()
        await refreshTasks()
        await refreshMemories()
        await refreshInbox()
        await refreshPreferences()
    }

    // MARK: tasks

    public func refreshTasks() async {
        do {
            openTasks = try await client?.tasks(status: "open") ?? []
            doneTasks = try await client?.tasks(status: "done") ?? []
        } catch { handle(error) }
    }

    public func addTask(_ title: String) async {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do { try await client?.createTask(title: trimmed); await refreshTasks() } catch { handle(error) }
    }

    /// Completes an open task, or reopens a finished one.
    public func toggle(_ task: KTask) async {
        do {
            if task.status == "done" { try await client?.reopenTask(id: task.id) } else { try await client?.completeTask(id: task.id) }
            await refreshTasks()
        } catch { handle(error) }
    }

    public func delete(_ task: KTask) async {
        do { try await client?.deleteTask(id: task.id); await refreshTasks() } catch { handle(error) }
    }

    // MARK: memory

    public func refreshMemories() async {
        do { memories = try await client?.memories() ?? [] } catch { handle(error) }
    }

    public func addMemory(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do { try await client?.createMemory(trimmed); await refreshMemories() } catch { handle(error) }
    }

    public func delete(_ memory: Memory) async {
        do { try await client?.deleteMemory(id: memory.id); await refreshMemories() } catch { handle(error) }
    }

    // MARK: inbox

    public func refreshInbox() async {
        do {
            if let result = try await client?.notifications() {
                notifications = result.items
                unreadCount = result.unread
            }
        } catch { handle(error) }
    }

    public func markRead(_ note: KNotification) async {
        guard !note.read else { return }
        do { try await client?.markNotificationRead(id: note.id); await refreshInbox() } catch { handle(error) }
    }

    public func markAllRead() async {
        do { try await client?.markAllNotificationsRead(); await refreshInbox() } catch { handle(error) }
    }

    // MARK: settings

    public func refreshPreferences() async {
        do { preferences = try await client?.preferences() } catch { handle(error) }
    }

    public func updatePreferences(responseStyle: String? = nil, tone: String? = nil, units: String? = nil,
                                  voiceReplies: Bool? = nil) async {
        do {
            preferences = try await client?.updatePreferences(responseStyle: responseStyle, tone: tone, units: units,
                                                              voiceReplies: voiceReplies)
        } catch { handle(error) }
    }

    public func refreshConversations() async {
        do { conversations = try await client?.conversations() ?? [] } catch { handle(error) }
    }

    public func refreshApprovals() async {
        do { pendingApprovals = try await client?.pendingApprovals() ?? [] } catch { handle(error) }
    }

    public func open(_ conversation: Conversation) async {
        currentConversationId = conversation.id
        do { messages = try await client?.messages(conversationId: conversation.id) ?? [] } catch { handle(error) }
    }

    public func newConversation() {
        streamTask?.cancel()
        currentConversationId = nil
        messages = []
    }

    public func delete(_ conversation: Conversation) async {
        do {
            try await client?.deleteConversation(id: conversation.id)
            if currentConversationId == conversation.id { newConversation() }
            await refreshConversations()
        } catch { handle(error) }
    }

    // MARK: chat

    public func send(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let client, !trimmed.isEmpty, !isReplying else { return }
        isReplying = true
        errorText = nil
        messages.append(ChatMessage(id: -1, role: "user", kind: "message", content: trimmed, status: "complete", createdAt: ""))
        messages.append(ChatMessage(id: -2, role: "assistant", kind: "message", content: "", status: "partial", createdAt: ""))

        streamTask = Task { [weak self] in
            guard let self else { return }
            do {
                for try await event in client.chatStream(message: trimmed, conversationId: currentConversationId) {
                    apply(event)
                }
            } catch is CancellationError {
                // Stopped by the user; the server keeps the partial reply.
            } catch {
                handle(error)
                // The reply may have been saved even though the connection dropped.
                if let id = currentConversationId { messages = (try? await client.messages(conversationId: id)) ?? messages }
            }
            isReplying = false
            statusText = ""
            await refreshConversations()
        }
    }

    public func stopReplying() { streamTask?.cancel() }

    func apply(_ event: ChatStreamEvent) {
        switch event {
        case .start(let id):
            currentConversationId = id
        case .delta(let text):
            if let index = messages.indices.last { messages[index].content += text }
        case .tool(let name, let status, let summary):
            statusText = "\(summary.isEmpty ? name : summary) — \(status.replacingOccurrences(of: "_", with: " "))"
        case .done(let message, let pending):
            if let index = messages.indices.last { messages[index] = message }
            pendingApprovals = (pendingApprovals + pending).uniqued()
        case .error(let text):
            errorText = text
        }
    }

    public func respond(to run: ToolRun, approve: Bool) async {
        do {
            _ = try await client?.respond(toApproval: run.id, approve: approve)
            pendingApprovals.removeAll { $0.id == run.id }
            if let id = currentConversationId { messages = try await client?.messages(conversationId: id) ?? messages }
        } catch { handle(error) }
    }

    // MARK: errors

    private func describe(_ error: Error) -> String {
        (error as? APIError)?.message ?? "Couldn't reach KYVON. Check your connection."
    }

    private func handle(_ error: Error) {
        if let api = error as? APIError, api.isUnauthorized {
            phase = .signedOut  // the token was revoked or expired
        }
        errorText = describe(error)
    }
}

extension Array where Element == ToolRun {
    func uniqued() -> [ToolRun] {
        var seen = Set<Int>()
        return filter { seen.insert($0.id).inserted }
    }
}
#endif
