import Foundation

/// Session ownership only. No recorder, file, URL or permission command.
struct CaptureBridgeMessage {
    enum Refusal: Error { case invalid }
    let command: String
    let document: String
    let owner: UUID
    let visit: UUID?
    let predecessor: UUID?
    init(_ raw: String) throws {
        guard raw.utf8.count <= 512, let data = raw.data(using:.utf8),
              let value = try JSONSerialization.jsonObject(with:data) as? [String:Any],
              let command = value["command"] as? String,
              ["capture_begin","capture_end","capture_connection"].contains(command),
              let document = value["document_id"] as? String,
              UUID(uuidString:document)?.uuidString.lowercased() == document,
              let text = value["owner"] as? String, let owner = UUID(uuidString:text),
              owner.uuidString.lowercased() == text else { throw Refusal.invalid }
        let base: Set<String> = ["command","document_id","owner"]
        if command == "capture_connection" {
            let keys = base.union(["visit"])
            guard Set(value.keys) == keys || Set(value.keys) == keys.union(["predecessor"]),
                  let visitText = value["visit"] as? String, let visit = UUID(uuidString:visitText),
                  visit.uuidString.lowercased() == visitText else { throw Refusal.invalid }
            self.visit = visit
            if let prior = value["predecessor"] {
                guard let text = prior as? String, let id = UUID(uuidString:text),
                      id.uuidString.lowercased() == text else { throw Refusal.invalid }
                predecessor = id
            } else { predecessor = nil }
        } else {
            guard Set(value.keys) == base else { throw Refusal.invalid }
            visit = nil; predecessor = nil
        }
        self.command = command; self.document = document; self.owner = owner
    }
}

/// Flat physical-connection CAS inside one existing microphone owner. IDs come
/// from the selected page; this is not proof of provider usage or new permission.
struct CaptureConnectionLease {
    private(set) var visit: UUID?
    private var predecessor: UUID?
    private var seen: Set<UUID> = []
    private(set) var generation = 0
    private(set) var expires: TimeInterval
    init(now: TimeInterval = ProcessInfo.processInfo.systemUptime) { expires = now + 600 }

    /// Initial binding and exact duplicate acknowledgments never extend time.
    /// Only a new successor of the current connection advances the600s lease.
    mutating func connect(_ next: UUID, from previous: UUID?, now: TimeInterval = ProcessInfo.processInfo.systemUptime) throws -> Bool {
        // Refuse expiry even if the main-actor timeout callback is still queued.
        guard now.isFinite, now >= 0, now < expires else { throw CaptureBridgeMessage.Refusal.invalid }
        if visit == next && predecessor == previous { return false }
        guard seen.count < 512, !seen.contains(next), previous == visit else {
            throw CaptureBridgeMessage.Refusal.invalid
        }
        let advances = visit != nil
        visit = next; predecessor = previous; seen.insert(next)
        if advances { generation += 1; expires = now + 600 }
        return advances
    }
}
