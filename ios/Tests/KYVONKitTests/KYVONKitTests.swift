import XCTest
@testable import KYVONKit

final class MockTransport: HTTPTransport, @unchecked Sendable {
    var requests: [URLRequest] = []
    var responses: [(Int, String)] = []
    var streamBody = ""

    func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        let (status, body) = responses.isEmpty ? (200, "{}") : responses.removeFirst()
        return (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }

    func bytes(for request: URLRequest) async throws -> (AsyncThrowingStream<UInt8, Error>, HTTPURLResponse) {
        requests.append(request)
        let (status, body) = responses.isEmpty ? (200, streamBody) : responses.removeFirst()
        let payload = Array(body.utf8)
        let stream = AsyncThrowingStream<UInt8, Error> { continuation in
            for byte in payload { continuation.yield(byte) }
            continuation.finish()
        }
        return (stream, HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!)
    }
}

final class KYVONKitTests: XCTestCase {
    let base = URL(string: "https://kyvon.example.com")!

    func testSSEParserHandlesSplitChunks() {
        var parser = SSEParser()
        XCTAssertTrue(parser.feed("event: delta\nda").isEmpty)
        let events = parser.feed("ta: {\"text\": \"Hi\"}\n\nevent: done\ndata: {}\n\n")
        XCTAssertEqual(events.map(\.event), ["delta", "done"])
        XCTAssertEqual(events[0].data, "{\"text\": \"Hi\"}")
    }

    func testSSEParserIgnoresCommentsAndCRLF() {
        var parser = SSEParser()
        let events = parser.feed(": keepalive\r\n\r\nevent: delta\r\ndata: {}\r\n\r\n")
        XCTAssertEqual(events.count, 1)
    }

    func testLoginStoresTokenAndSendsBearerAfterwards() async throws {
        let transport = MockTransport()
        transport.responses = [
            (200, #"{"user": {"id": 1, "username": "owner"}, "token": "kyv_secret", "expires_at": "2026-12-01T00:00:00+00:00"}"#),
            (200, #"{"conversations": []}"#),
        ]
        let store = InMemoryTokenStore()
        let client = APIClient(baseURL: base, tokens: store, transport: transport)
        let user = try await client.login(username: "owner", password: "pw", deviceName: "iPad")
        XCTAssertEqual(user.username, "owner")
        XCTAssertEqual(store.load(), "kyv_secret")
        XCTAssertNil(transport.requests[0].value(forHTTPHeaderField: "Authorization"), "login sends no token")
        _ = try await client.conversations()
        XCTAssertEqual(transport.requests[1].value(forHTTPHeaderField: "Authorization"), "Bearer kyv_secret")
        XCTAssertEqual(transport.requests[1].url?.path, "/api/v1/conversations")
    }

    func testLoginBodyUsesSnakeCase() async throws {
        let transport = MockTransport()
        transport.responses = [(200, #"{"user": {"id": 1, "username": "o"}, "token": "t", "expires_at": "x"}"#)]
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(), transport: transport)
        _ = try await client.login(username: "o", password: "p", deviceName: "Phone")
        let body = String(data: transport.requests[0].httpBody!, encoding: .utf8)!
        XCTAssertTrue(body.contains("\"device_name\""))
    }

    func testErrorEnvelopeBecomesAPIError() async {
        let transport = MockTransport()
        transport.responses = [(401, #"{"error": {"code": "invalid_credentials", "message": "Invalid username or password."}}"#)]
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(), transport: transport)
        do {
            _ = try await client.login(username: "o", password: "bad", deviceName: "d")
            XCTFail("expected an error")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "invalid_credentials")
            XCTAssertTrue(error.isUnauthorized)
        } catch { XCTFail("wrong error \(error)") }
    }

    func testLogoutClearsTheTokenEvenIfTheServerCallFails() async {
        let transport = MockTransport()
        transport.responses = [(500, "oops")]
        let store = InMemoryTokenStore(token: "kyv_x")
        let client = APIClient(baseURL: base, tokens: store, transport: transport)
        await client.logout()
        XCTAssertNil(store.load())
    }

    func testChatStreamYieldsEventsInOrder() async throws {
        let transport = MockTransport()
        transport.streamBody = """
        event: start
        data: {"conversation": {"id": 7, "title": "t", "archived": false, "updated_at": "x"}, "user_message": {}}

        event: delta
        data: {"text": "Hel"}

        event: delta
        data: {"text": "lo"}

        event: tool
        data: {"name": "task_create", "status": "succeeded", "summary": "Add task"}

        event: done
        data: {"message": {"id": 3, "role": "assistant", "kind": "message", "content": "Hello", "status": "complete", "created_at": "x"}, "flags": {"pending_confirmations": [{"id": 9, "tool": "calendar_create_event", "status": "pending_confirmation", "risk": "external", "summary": "Add event"}]}}


        """
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(token: "t"), transport: transport)
        var events: [ChatStreamEvent] = []
        for try await event in client.chatStream(message: "hi", conversationId: nil) { events.append(event) }
        XCTAssertEqual(events.count, 5)
        XCTAssertEqual(events[0], .start(conversationId: 7))
        XCTAssertEqual(events[1], .delta("Hel"))
        XCTAssertEqual(events[3], .tool(name: "task_create", status: "succeeded", summary: "Add task"))
        guard case .done(let message, let pending) = events[4] else { return XCTFail("no done event") }
        XCTAssertEqual(message.content, "Hello")
        XCTAssertEqual(pending.first?.summary, "Add event")
        XCTAssertEqual(transport.requests[0].url?.path, "/api/v1/chat/stream")
    }

    func testChatStreamSurfacesHTTPErrors() async {
        let transport = MockTransport()
        transport.responses = [(400, #"{"error": {"code": "invalid_request", "message": "Empty message."}}"#)]
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(token: "t"), transport: transport)
        do {
            for try await _ in client.chatStream(message: " ", conversationId: nil) {}
            XCTFail("expected an error")
        } catch let error as APIError { XCTAssertEqual(error.message, "Empty message.") } catch { XCTFail("\(error)") }
    }

    func testApprovalRequestsHitTheRightEndpoints() async throws {
        let transport = MockTransport()
        let run = #"{"tool_run": {"id": 4, "tool": "x", "status": "succeeded", "risk": "external", "summary": "s"}}"#
        transport.responses = [(200, run), (200, run)]
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(token: "t"), transport: transport)
        _ = try await client.respond(toApproval: 4, approve: true)
        _ = try await client.respond(toApproval: 4, approve: false)
        XCTAssertEqual(transport.requests.map { $0.url!.path }, ["/api/v1/tool-runs/4/confirm", "/api/v1/tool-runs/4/reject"])
        XCTAssertEqual(transport.requests[0].httpMethod, "POST")
    }

    func testVoiceUploadIsMultipart() async throws {
        let transport = MockTransport()
        transport.responses = [(200, #"{"text": "hello there"}"#)]
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(token: "t"), transport: transport)
        let text = try await client.transcribe(audio: Data([1, 2, 3]), filename: "voice.m4a", mimeType: "audio/mp4")
        XCTAssertEqual(text, "hello there")
        let request = transport.requests[0]
        XCTAssertTrue(request.value(forHTTPHeaderField: "Content-Type")!.hasPrefix("multipart/form-data; boundary="))
        XCTAssertNotNil(String(data: request.httpBody!, encoding: .isoLatin1)?.range(of: "name=\"audio\"; filename=\"voice.m4a\""))
    }

    func testPushTokenAndLocationPayloads() async throws {
        let transport = MockTransport()
        let client = APIClient(baseURL: base, tokens: InMemoryTokenStore(token: "t"), transport: transport)
        try await client.registerPushToken("abcd1234")
        try await client.shareLocation(latitude: 1.5, longitude: -2.5)
        XCTAssertEqual(transport.requests[0].url?.path, "/api/v1/push/apns")
        XCTAssertTrue(String(data: transport.requests[0].httpBody!, encoding: .utf8)!.contains("\"device_token\":\"abcd1234\""))
        XCTAssertEqual(transport.requests[1].url?.path, "/api/v1/environment")
    }
}
