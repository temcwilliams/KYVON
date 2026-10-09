import Foundation

/// Events of `POST /chat/stream`.
public enum ChatStreamEvent: Equatable, Sendable {
    case start(conversationId: Int)
    case delta(String)
    case tool(name: String, status: String, summary: String)
    case done(message: ChatMessage, pending: [ToolRun])
    case error(String)
}

/// Incremental Server-Sent Events parser. Feed it bytes as they arrive; it returns the
/// complete events found so far and keeps any partial event for the next call.
public struct SSEParser {
    public struct Raw: Equatable, Sendable {
        public let event: String
        public let data: String
    }

    private var buffer = ""

    public init() {}

    public mutating func feed(_ chunk: String) -> [Raw] {
        buffer += chunk.replacingOccurrences(of: "\r\n", with: "\n")
        var events: [Raw] = []
        while let range = buffer.range(of: "\n\n") {
            let block = String(buffer[buffer.startIndex..<range.lowerBound])
            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
            var name = "message"
            var data: [String] = []
            for line in block.split(separator: "\n", omittingEmptySubsequences: false) {
                if line.hasPrefix("event: ") { name = String(line.dropFirst(7)) }
                else if line.hasPrefix("data: ") { data.append(String(line.dropFirst(6))) }
            }
            if !data.isEmpty { events.append(Raw(event: name, data: data.joined(separator: "\n"))) }
        }
        return events
    }
}

enum ChatEventDecoder {
    private struct Start: Decodable { let conversation: Conversation }
    private struct Delta: Decodable { let text: String }
    private struct Tool: Decodable { let name: String; let status: String; let summary: String? }
    private struct Done: Decodable {
        let message: ChatMessage
        let flags: Flags?
        struct Flags: Decodable { let pendingConfirmations: [ToolRun]? }
    }
    private struct Failure: Decodable { let message: String }

    static func decode(_ raw: SSEParser.Raw, decoder: JSONDecoder) -> ChatStreamEvent? {
        let data = Data(raw.data.utf8)
        switch raw.event {
        case "start":
            return (try? decoder.decode(Start.self, from: data)).map { .start(conversationId: $0.conversation.id) }
        case "delta":
            return (try? decoder.decode(Delta.self, from: data)).map { .delta($0.text) }
        case "tool":
            return (try? decoder.decode(Tool.self, from: data)).map { .tool(name: $0.name, status: $0.status, summary: $0.summary ?? "") }
        case "done":
            return (try? decoder.decode(Done.self, from: data)).map {
                .done(message: $0.message, pending: $0.flags?.pendingConfirmations ?? [])
            }
        case "error":
            return (try? decoder.decode(Failure.self, from: data)).map { .error($0.message) }
        default:
            return nil
        }
    }
}
