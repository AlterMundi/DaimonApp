import Foundation

/// User-selected HTTPS service location, not an account or resource grant.
public struct InteractionHome: Equatable {
    public enum Refusal: Error { case invalidHome }
    public let origin: URL
    public let conversation: URL
    public init(_ text: String) throws {
        guard var parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.port == nil || parts.port == 443, ["", "/", "/interaction/"].contains(parts.path)
        else { throw Refusal.invalidHome }
        parts.scheme = "https"; parts.host = host.lowercased(); parts.port = nil; parts.path = ""
        guard let origin = parts.url,
              let conversation = URL(string: "/interaction/?view=conversation&client=standalone", relativeTo: origin)?.absoluteURL
        else { throw Refusal.invalidHome }
        self.origin = origin; self.conversation = conversation
    }
    public func allowsPage(_ url: URL) -> Bool {
        guard url.scheme == "https", url.host?.lowercased() == origin.host?.lowercased(),
              url.port == nil || url.port == 443, url.user == nil, url.password == nil,
              url.path.hasPrefix("/interaction/"),
              !url.path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." }) else { return false }
        return true
    }
}
