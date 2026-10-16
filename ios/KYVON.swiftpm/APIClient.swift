import Foundation

public struct APIError: Error, Equatable, LocalizedError, Sendable {
    public let status: Int
    public let code: String
    public let message: String
    public var errorDescription: String? { message }
    public var isUnauthorized: Bool { status == 401 }
}

/// The network layer, injectable so tests never touch the network.
public protocol HTTPTransport: Sendable {
    func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse)
    func bytes(for request: URLRequest) async throws -> (AsyncThrowingStream<UInt8, Error>, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport {
    private let session: URLSession
    public init(session: URLSession = .shared) { self.session = session }

    public func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (data, http)
    }

    public func bytes(for request: URLRequest) async throws -> (AsyncThrowingStream<UInt8, Error>, HTTPURLResponse) {
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        let stream = AsyncThrowingStream<UInt8, Error> { continuation in
            let task = Task {
                do {
                    for try await byte in bytes { continuation.yield(byte) }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
        return (stream, http)
    }
}

/// A thin client for the KYVON API. It holds no assistant logic: it sends requests, decodes
/// responses, and turns the server's error envelope into `APIError`.
public final class APIClient: @unchecked Sendable {
    public let baseURL: URL
    private let transport: HTTPTransport
    private let tokens: TokenStore
    let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    public init(baseURL: URL, tokens: TokenStore, transport: HTTPTransport = URLSessionTransport()) {
        self.baseURL = baseURL
        self.tokens = tokens
        self.transport = transport
    }

    // MARK: requests

    func makeRequest(_ method: String, _ path: String, query: [String: String] = [:], body: Data? = nil,
                     contentType: String = "application/json", authenticated: Bool = true) -> URLRequest {
        var components = URLComponents(url: baseURL.appendingPathComponent("api/v1" + path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body { request.httpBody = body; request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if authenticated, let token = tokens.load() { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return request
    }

    func body<T: Encodable>(_ value: T) throws -> Data { try encoder.encode(value) }

    func send<T: Decodable>(_ request: URLRequest, as type: T.Type = T.self) async throws -> T {
        let (data, response) = try await transport.data(for: request)
        try check(response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    func check(_ response: HTTPURLResponse, data: Data) throws {
        guard !(200..<300).contains(response.statusCode) else { return }
        struct Envelope: Decodable { struct Body: Decodable { let code: String; let message: String }; let error: Body }
        if let envelope = try? decoder.decode(Envelope.self, from: data) {
            throw APIError(status: response.statusCode, code: envelope.error.code, message: envelope.error.message)
        }
        throw APIError(status: response.statusCode, code: "http_error", message: "The server returned \(response.statusCode).")
    }

    // MARK: authentication

    /// Signs in and stores the per-device token in the token store (the Keychain in the app).
    public func login(username: String, password: String, deviceName: String) async throws -> APIUser {
        struct Body: Encodable { let username: String; let password: String; let deviceName: String }
        let request = makeRequest("POST", "/auth/login", body: try body(Body(username: username, password: password, deviceName: deviceName)), authenticated: false)
        let response: LoginResponse = try await send(request)
        guard let token = response.token else { throw APIError(status: 500, code: "no_token", message: "The server did not return a token.") }
        try tokens.save(token)
        return response.user
    }

    public func logout() async {
        _ = try? await send(makeRequest("POST", "/auth/logout"), as: OkEnvelope.self)
        tokens.clear()
    }

    public func currentUser() async throws -> APIUser {
        struct Envelope: Decodable { let user: APIUser }
        return try await send(makeRequest("GET", "/auth/me"), as: Envelope.self).user
    }

    public var hasToken: Bool { tokens.load() != nil }

    // MARK: conversations and chat

    public func conversations() async throws -> [Conversation] {
        try await send(makeRequest("GET", "/conversations"), as: ConversationsEnvelope.self).conversations
    }

    public func messages(conversationId: Int) async throws -> [ChatMessage] {
        try await send(makeRequest("GET", "/conversations/\(conversationId)/messages"), as: MessagesEnvelope.self).messages
    }

    public func deleteConversation(id: Int) async throws {
        _ = try await send(makeRequest("DELETE", "/conversations/\(id)"), as: OkEnvelope.self)
    }

    /// Streams one chat turn. The server saves the reply (even a partial one) whatever happens,
    /// so after a dropped connection `messages(conversationId:)` shows what was kept.
    public func chatStream(message: String, conversationId: Int?) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task { [self] in
                do {
                    struct Body: Encodable { let message: String; let conversationId: Int? }
                    let request = makeRequest("POST", "/chat/stream", body: try body(Body(message: message, conversationId: conversationId)))
                    let (bytes, response) = try await transport.bytes(for: request)
                    if !(200..<300).contains(response.statusCode) {
                        var data = Data()
                        for try await byte in bytes { data.append(byte) }
                        try check(response, data: data)
                    }
                    var parser = SSEParser()
                    var pending = Data()
                    for try await byte in bytes {
                        pending.append(byte)
                        // Decode only on complete UTF-8 sequences.
                        if let text = String(data: pending, encoding: .utf8) {
                            pending.removeAll(keepingCapacity: true)
                            for raw in parser.feed(text) {
                                if let event = ChatEventDecoder.decode(raw, decoder: decoder) { continuation.yield(event) }
                            }
                        }
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: approvals, memory, tasks, notifications

    public func pendingApprovals() async throws -> [ToolRun] {
        try await send(makeRequest("GET", "/tool-runs/pending"), as: ToolRunsEnvelope.self).toolRuns
    }

    public func respond(toApproval id: Int, approve: Bool) async throws -> ToolRun {
        try await send(makeRequest("POST", "/tool-runs/\(id)/\(approve ? "confirm" : "reject")"), as: ToolRunEnvelope.self).toolRun
    }

    public func memories() async throws -> [Memory] {
        try await send(makeRequest("GET", "/memories"), as: MemoriesEnvelope.self).memories
    }

    public func tasks(status: String = "open") async throws -> [KTask] {
        try await send(makeRequest("GET", "/tasks", query: ["status": status]), as: TasksEnvelope.self).tasks
    }

    public func completeTask(id: Int) async throws {
        _ = try await send(makeRequest("POST", "/tasks/\(id)/complete"), as: OkEnvelope.self)
    }

    public func notifications() async throws -> (items: [KNotification], unread: Int) {
        let result = try await send(makeRequest("GET", "/notifications"), as: NotificationsEnvelope.self)
        return (result.notifications, result.unreadCount)
    }

    // MARK: hosted accounts

    /// Public: which mode the server is in and whether sign-up is open.
    public func publicConfig() async throws -> PublicConfig {
        try await send(makeRequest("GET", "/config", authenticated: false), as: PublicConfig.self)
    }

    /// Creates an account. The answer is the same whether or not the email was already registered.
    public func signUp(email: String, password: String, acceptTerms: Bool) async throws -> String {
        struct Body: Encodable { let email: String; let password: String; let acceptTerms: Bool }
        struct Reply: Decodable { let message: String? }
        let body = try body(Body(email: email, password: password, acceptTerms: acceptTerms))
        let reply = try await send(makeRequest("POST", "/auth/signup", body: body, authenticated: false), as: Reply.self)
        return reply.message ?? "Check your email to finish creating your account."
    }

    public func forgotPassword(email: String) async throws -> String {
        struct Body: Encodable { let email: String }
        struct Reply: Decodable { let message: String? }
        let body = try body(Body(email: email))
        let reply = try await send(makeRequest("POST", "/auth/forgot-password", body: body, authenticated: false), as: Reply.self)
        return reply.message ?? "If that address has an account, we sent a link to reset the password."
    }

    public func resendVerification() async throws {
        _ = try await send(makeRequest("POST", "/auth/resend-verification"), as: OkEnvelope.self)
    }

    public func account() async throws -> AccountInfo {
        try await send(makeRequest("GET", "/account"), as: AccountInfo.self)
    }

    public func changePassword(current: String, new: String) async throws {
        struct Body: Encodable { let currentPassword: String; let newPassword: String }
        let body = try body(Body(currentPassword: current, newPassword: new))
        _ = try await send(makeRequest("POST", "/account/change-password", body: body), as: OkEnvelope.self)
    }

    /// Permanently deletes the account and its data. Needs the password again.
    public func deleteAccount(password: String) async throws {
        struct Body: Encodable { let password: String }
        let body = try body(Body(password: password))
        _ = try await send(makeRequest("DELETE", "/account", body: body), as: OkEnvelope.self)
        tokens.clear()
    }

    // MARK: tasks, memory, inbox, settings

    public func createTask(title: String, priority: String = "normal") async throws {
        struct Body: Encodable { let title: String; let priority: String }
        _ = try await send(makeRequest("POST", "/tasks", body: try body(Body(title: title, priority: priority))), as: OkEnvelope.self)
    }

    public func reopenTask(id: Int) async throws {
        _ = try await send(makeRequest("POST", "/tasks/\(id)/reopen"), as: OkEnvelope.self)
    }

    public func deleteTask(id: Int) async throws {
        _ = try await send(makeRequest("DELETE", "/tasks/\(id)"), as: OkEnvelope.self)
    }

    /// Saves a memory the user asked for. (The server refuses anything that looks like a secret.)
    public func createMemory(_ text: String) async throws {
        struct Body: Encodable { let text: String }
        _ = try await send(makeRequest("POST", "/memories", body: try body(Body(text: text))), as: OkEnvelope.self)
    }

    public func deleteMemory(id: Int) async throws {
        _ = try await send(makeRequest("DELETE", "/memories/\(id)"), as: OkEnvelope.self)
    }

    public func markNotificationRead(id: Int) async throws {
        _ = try await send(makeRequest("POST", "/notifications/\(id)/read"), as: OkEnvelope.self)
    }

    public func markAllNotificationsRead() async throws {
        _ = try await send(makeRequest("POST", "/notifications/read-all"), as: OkEnvelope.self)
    }

    public func preferences() async throws -> Preferences {
        try await send(makeRequest("GET", "/settings"), as: SettingsEnvelope.self).settings
    }

    /// Changes only the fields that are non-nil.
    public func updatePreferences(responseStyle: String? = nil, tone: String? = nil, units: String? = nil,
                                  voiceReplies: Bool? = nil) async throws -> Preferences {
        struct Patch: Encodable { var responseStyle: String?; var tone: String?; var units: String?; var voiceReplies: Bool? }
        let patch = Patch(responseStyle: responseStyle, tone: tone, units: units, voiceReplies: voiceReplies)
        return try await send(makeRequest("PATCH", "/settings", body: try body(patch)), as: SettingsEnvelope.self).settings
    }

    // MARK: device features

    /// Shares the device location so KYVON can use local weather and time zone.
    public func shareLocation(latitude: Double, longitude: Double) async throws {
        struct Body: Encodable { let latitude: Double; let longitude: Double }
        _ = try await send(makeRequest("POST", "/environment", body: try body(Body(latitude: latitude, longitude: longitude))), as: OkEnvelope.self)
    }

    public func setTimezone(_ identifier: String) async throws {
        struct Body: Encodable { let detectedTimezone: String }
        _ = try await send(makeRequest("PATCH", "/settings", body: try body(Body(detectedTimezone: identifier))), as: OkEnvelope.self)
    }

    /// Registers the APNs device token so the server can send push notifications.
    public func registerPushToken(_ hexToken: String) async throws {
        struct Body: Encodable { let deviceToken: String }
        _ = try await send(makeRequest("POST", "/push/apns", body: try body(Body(deviceToken: hexToken))), as: OkEnvelope.self)
    }

    /// Speech to text on the server (Whisper). `audio` is the recorded file's bytes.
    public func transcribe(audio: Data, filename: String, mimeType: String) async throws -> String {
        let boundary = "kyvon-\(UUID().uuidString)"
        var form = Data()
        form.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"\(filename)\"\r\nContent-Type: \(mimeType)\r\n\r\n".utf8))
        form.append(audio)
        form.append(Data("\r\n--\(boundary)--\r\n".utf8))
        let request = makeRequest("POST", "/voice/transcribe", body: form, contentType: "multipart/form-data; boundary=\(boundary)")
        return try await send(request, as: TranscriptionEnvelope.self).text
    }
}
