import Foundation

/// Decoder-worker input matching Android's VerifiedAudioBuffer. A verified
/// prefix is readable before the terminal digest; missing data is never EOF.
/// This does not perform networking, decode/play audio or authorize a session.
final class VerifiedEncodedAudioSource: @unchecked Sendable {
    enum Refusal: Error { case invalid, closed, stalled }
    static let maximumBytes = 8 * 1024 * 1024
    static let maximumChunkBytes = 32768
    private let condition = NSCondition()
    private let maximum: Int
    private let waitSeconds: TimeInterval
    private let expires: TimeInterval
    // One flat bounded allocation avoids per-chunk metadata growth when a
    // sender supplies many tiny, otherwise valid chunks.
    private var bytes = Data()
    private var sequence = 0
    private var terminal = false
    private var closed = false

    init(maximum: Int = VerifiedEncodedAudioSource.maximumBytes, waitSeconds: TimeInterval = 30,
         lifetimeSeconds: TimeInterval = 145) throws {
        guard (1...Self.maximumBytes).contains(maximum), waitSeconds.isFinite,
              waitSeconds > 0, waitSeconds <= 30, lifetimeSeconds.isFinite,
              lifetimeSeconds > 0, lifetimeSeconds <= 145 else { throw Refusal.invalid }
        self.maximum = maximum; self.waitSeconds = waitSeconds
        expires = ProcessInfo.processInfo.systemUptime + lifetimeSeconds
    }
    private func retire() {
        closed = true; bytes = Data(); condition.broadcast()
    }
    func append(sequence next: Int, data: Data, sha256: String) throws {
        condition.lock(); defer { condition.unlock() }
        guard !closed, !terminal, next == sequence, !data.isEmpty,
              data.count <= Self.maximumChunkBytes, data.count <= maximum - bytes.count,
              PCMPlaybackQueue.digest(data) == sha256 else {
            retire(); throw Refusal.invalid
        }
        bytes.append(data); sequence += 1; condition.broadcast()
    }
    func finish(bytes expected: Int, sha256: String) throws {
        condition.lock(); defer { condition.unlock() }
        guard !closed, !terminal, !bytes.isEmpty, expected == bytes.count,
              PCMPlaybackQueue.digest(bytes) == sha256 else {
            retire(); throw Refusal.invalid
        }
        terminal = true; condition.broadcast()
    }
    var size: Int? {
        condition.lock(); defer { condition.unlock() }
        return terminal && !closed ? bytes.count : nil
    }
    /// Runs on the decoder's worker, never the UI/audio callback thread.
    /// nil means verified terminal EOF; an incomplete/stopped source throws.
    func read(at position: Int, length: Int) throws -> Data? {
        condition.lock(); defer { condition.unlock() }
        guard position >= 0, position <= maximum,
              (0...Self.maximumChunkBytes).contains(length) else {
            retire(); throw Refusal.invalid
        }
        guard !closed else { throw Refusal.closed }
        if length == 0 { return Data() }
        let deadline = min(expires, ProcessInfo.processInfo.systemUptime + waitSeconds)
        while !closed && !terminal && position >= bytes.count {
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            guard remaining > 0 else { retire(); throw Refusal.stalled }
            _ = condition.wait(until: Date(timeIntervalSinceNow: remaining))
        }
        guard !closed else { throw Refusal.closed }
        if position >= bytes.count { return nil }
        let end = position + min(length, bytes.count - position)
        return bytes.subdata(in: position..<end)
    }
    func close() {
        condition.lock(); defer { condition.unlock() }
        retire()
    }
}
