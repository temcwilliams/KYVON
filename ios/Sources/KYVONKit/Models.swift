import Foundation

// Wire models for /api/v1. Field names follow the server's JSON (snake_case, decoded with
// .convertFromSnakeCase). Dates stay ISO-8601 strings: the server is the source of truth and
// the client only displays them.

public struct APIUser: Codable, Equatable, Sendable {
    public let id: Int
    public let username: String
}

public struct LoginResponse: Codable, Sendable {
    public let user: APIUser
    public let token: String?
    public let expiresAt: String
}

public struct Conversation: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public var title: String
    public let archived: Bool
    public let updatedAt: String
    public let messageCount: Int?
}

public struct ChatMessage: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let role: String
    public let kind: String
    public var content: String
    public let status: String
    public let createdAt: String

    // Public so the app can create the placeholder rows shown while a reply streams in.
    public init(id: Int, role: String, kind: String, content: String, status: String, createdAt: String) {
        self.id = id; self.role = role; self.kind = kind
        self.content = content; self.status = status; self.createdAt = createdAt
    }
}

public struct Memory: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public var memory: String
    public let category: String
    public let importance: Int
    public let source: String
}

public struct KTask: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public var title: String
    public let notes: String
    public let status: String
    public let priorityName: String
    public let due: String?
    public let overdue: Bool
}

/// An action KYVON wants to take that needs the user's approval.
public struct ToolRun: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let tool: String
    public let status: String
    public let risk: String
    public let summary: String
    public let conversationId: Int?
}

public struct KNotification: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let title: String
    public let body: String
    public let read: Bool
    public let conversationId: Int?
    public let createdAt: String
}

// Response envelopes
struct ConversationsEnvelope: Codable { let conversations: [Conversation] }
struct ConversationEnvelope: Codable { let conversation: Conversation }
struct MessagesEnvelope: Codable { let messages: [ChatMessage] }
struct MemoriesEnvelope: Codable { let memories: [Memory] }
struct TasksEnvelope: Codable { let tasks: [KTask] }
struct ToolRunEnvelope: Codable { let toolRun: ToolRun }
struct ToolRunsEnvelope: Codable { let toolRuns: [ToolRun] }
struct NotificationsEnvelope: Codable { let notifications: [KNotification]; let unreadCount: Int }
struct TranscriptionEnvelope: Codable { let text: String }
struct OkEnvelope: Codable { let ok: Bool? }
