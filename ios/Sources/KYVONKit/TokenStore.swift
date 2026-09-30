import Foundation
#if canImport(Security)
import Security
#endif

/// Where the device token lives. The real implementation is the Keychain: the token is never
/// written to UserDefaults, files or logs.
public protocol TokenStore: AnyObject {
    func load() -> String?
    func save(_ token: String) throws
    func clear()
}

public final class InMemoryTokenStore: TokenStore {
    private var token: String?
    public init(token: String? = nil) { self.token = token }
    public func load() -> String? { token }
    public func save(_ token: String) throws { self.token = token }
    public func clear() { token = nil }
}

#if canImport(Security)
public final class KeychainTokenStore: TokenStore {
    public struct KeychainError: Error { public let status: OSStatus }

    private let service: String
    private let account = "device-token"

    public init(service: String = "app.kyvon.token") { self.service = service }

    private var baseQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    public func load() -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public func save(_ token: String) throws {
        clear()
        var query = baseQuery
        query[kSecValueData as String] = Data(token.utf8)
        // Available after the first unlock, and never migrated to another device or a backup.
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(query as CFDictionary, nil)
        if status != errSecSuccess { throw KeychainError(status: status) }
    }

    public func clear() {
        SecItemDelete(baseQuery as CFDictionary)
    }
}
#endif
