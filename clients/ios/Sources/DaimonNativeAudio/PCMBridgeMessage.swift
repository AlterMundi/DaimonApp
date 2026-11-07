import CoreFoundation
import Foundation

/// Closed numeric/data wire contract shared with the existing native-audio.js.
struct PCMBridgeMessage {
    enum Refusal: Error { case invalid }
    let command: String
    let document: String
    let id: String?
    let fields: [String: Any]
    init(_ raw: String) throws {
        guard raw.utf8.count <= 45000, let data = raw.data(using: .utf8),
              let fields = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let command = fields["command"] as? String, let document = fields["document_id"] as? String,
              UUID(uuidString: document)?.uuidString.lowercased() == document else { throw Refusal.invalid }
        let extras: Set<String>
        switch command {
        case "hello": extras = []
        case "session":
            extras = ["enabled"]
            guard let enabled = fields["enabled"] as? NSNumber,
                  CFGetTypeID(enabled) == CFBooleanGetTypeID() else { throw Refusal.invalid }
        case "pcm_begin": extras = ["id", "seconds"]
        case "pcm_chunk": extras = ["id", "sequence", "utterance", "end", "data", "sha256"]
        case "pcm_flush", "pause", "play", "stop": extras = ["id"]
        default: throw Refusal.invalid
        }
        guard Set(fields.keys) == extras.union(["command", "document_id"]) else { throw Refusal.invalid }
        let id = fields["id"] as? String
        if extras.contains("id") {
            guard let id, id.range(of: "^pcm_[1-9][0-9]{0,15}$", options: .regularExpression) != nil else { throw Refusal.invalid }
        }
        self.command = command; self.document = document; self.id = id; self.fields = fields
    }
    func integer(_ key: String, _ range: ClosedRange<Int>) throws -> Int {
        guard let value = fields[key] as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite, value.doubleValue.rounded() == value.doubleValue,
              value.doubleValue >= Double(range.lowerBound), value.doubleValue <= Double(range.upperBound)
        else { throw Refusal.invalid }
        return value.intValue
    }
}
