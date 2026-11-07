import CryptoKit
import Foundation

/// Verified 24 kHz mono PCM16 spans for one serial native output owner.
/// Enqueuing or scheduling bytes is not evidence that a device played them.
public final class PCMPlaybackQueue {
    public enum Refusal: Error { case invalidDuration, invalidSpan, invalidPosition }
    public struct Pending {
        public let utterance: String
        public let data: Data
    }
    private final class Span {
        let utterance: String
        let begin: Int
        let end: Int
        let sourceBegin: Int
        var data: Data?
        var written = 0
        init(utterance: String, begin: Int, sourceBegin: Int, data: Data) {
            self.utterance = utterance; self.begin = begin; self.end = begin + data.count
            self.sourceBegin = sourceBegin; self.data = data
        }
    }
    public static let maximumQueuedBytes = 30 * 48000
    private let maximumSessionBytes: Int
    private var writes: [Span] = []
    private var spans: [Span] = []
    private var received: [String: Int] = [:]
    private var reported: [String: Int] = [:]
    private var retired: Set<String> = []
    public private(set) var sequence = 0
    public private(set) var lifetimeBytes = 0
    public private(set) var appendedBytes = 0
    public private(set) var submittedBytes = 0
    public private(set) var playedBytes = 0
    public var queuedBytes: Int { appendedBytes - playedBytes }

    public init(seconds: Int = 300) throws {
        guard (300...600).contains(seconds) else { throw Refusal.invalidDuration }
        maximumSessionBytes = seconds * 48000
    }

    public func append(sequence next: Int, utterance: String, end: Int, data: Data, sha256: String) throws {
        guard UUID(uuidString: utterance)?.uuidString.lowercased() == utterance,
              next == sequence, (2...32768).contains(data.count), data.count.isMultiple(of: 2),
              sha256 == Self.digest(data), !retired.contains(utterance),
              received[utterance] != nil || received.count < 128,
              spans.count < 512, lifetimeBytes <= maximumSessionBytes - data.count,
              queuedBytes <= Self.maximumQueuedBytes - data.count,
              end == (received[utterance] ?? 0) + data.count else { throw Refusal.invalidSpan }
        let span = Span(utterance: utterance, begin: appendedBytes,
                        sourceBegin: received[utterance] ?? 0, data: data)
        writes.append(span); spans.append(span); received[utterance] = end
        appendedBytes += data.count; lifetimeBytes += data.count; sequence += 1
    }

    public static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    public func next() -> Pending? {
        guard let span = writes.first, let data = span.data else { return nil }
        return Pending(utterance: span.utterance, data: data.subdata(in: span.written..<data.count))
    }

    public func submitted(_ bytes: Int) throws {
        guard let span = writes.first, bytes >= 0, bytes.isMultiple(of: 2),
              bytes <= span.end - span.begin - span.written else { throw Refusal.invalidPosition }
        span.written += bytes; submittedBytes += bytes
        if span.written == span.end - span.begin { span.data = nil; writes.removeFirst() }
    }

    /// Caller supplies the current owner's observed rendered/playback position,
    /// never its scheduled-byte count. Epoch/lifecycle fencing belongs to the driver.
    public func advance(to position: Int) throws -> [String: Int] {
        guard position >= playedBytes, position <= submittedBytes, position.isMultiple(of: 2)
        else { throw Refusal.invalidPosition }
        playedBytes = position
        var changed: [String: Int] = [:]
        for span in spans {
            if position <= span.begin { break }
            let count = span.sourceBegin + min(position, span.end) - span.begin
            if count > (reported[span.utterance] ?? 0) {
                reported[span.utterance] = count; changed[span.utterance] = count
            }
        }
        spans.removeAll { $0.end <= position }
        return changed
    }

    /// Retire queued sound, preserving lifetime/sequence/source fences. A later
    /// utterance cannot revive cancelled bytes or acquire a fresh session budget.
    public func flush() {
        retired.formUnion(received.keys); writes.removeAll(); spans.removeAll()
        appendedBytes = 0; submittedBytes = 0; playedBytes = 0
    }
}
