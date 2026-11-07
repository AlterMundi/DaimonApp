import Foundation

protocol PCMOutputDevice: AnyObject {
    func prepare() throws
    func schedule(_ data: Data, completion: @escaping () -> Void) throws
    func start() throws
    func pause()
    func stop()
}

/// One foreground PCM owner. The hosting client supplies its explicit audio
/// session activation/deactivation and closes this owner on lifecycle/route loss.
@MainActor public final class PCMPlaybackDriver {
    public enum Event {
        case ready, playing, paused, quiet, closed
        case progress([String: Int])
        case unavailable
    }
    public enum Refusal: Error { case closed, expired }
    private struct Ticket { let id: UUID; let end: Int; var complete = false }
    private let queue: PCMPlaybackQueue
    private let device: PCMOutputDevice
    private let activate: () throws -> Void
    private let deactivate: () -> Void
    private let emit: (Event) -> Void
    private let clock: () -> TimeInterval
    private let expires: TimeInterval
    private var deadline: DispatchWorkItem?
    private var tickets: [Ticket] = []
    private var epoch = UUID()
    private var active = false
    private var paused = false
    private var closed = false
    private var reportedPlaying = false

    public convenience init(seconds: Int = 300, activate: @escaping () throws -> Void,
                            deactivate: @escaping () -> Void, emit: @escaping (Event) -> Void) throws {
        try self.init(seconds: seconds, device: ApplePCMOutput(), activate: activate,
                      deactivate: deactivate, clock: { ProcessInfo.processInfo.systemUptime }, emit: emit)
    }
    init(seconds: Int, device: PCMOutputDevice, activate: @escaping () throws -> Void,
         deactivate: @escaping () -> Void, clock: @escaping () -> TimeInterval,
         emit: @escaping (Event) -> Void) throws {
        queue = try PCMPlaybackQueue(seconds: seconds)
        self.device = device; self.activate = activate; self.deactivate = deactivate
        self.clock = clock; self.emit = emit; expires = clock() + Double(seconds)
        try device.prepare()
        let work = DispatchWorkItem { [weak self] in Task { @MainActor in self?.close() } }
        deadline = work; DispatchQueue.main.asyncAfter(deadline: .now() + Double(seconds), execute: work)
        emit(.ready)
    }
    private func check() throws {
        guard !closed else { throw Refusal.closed }
        guard clock() < expires else { close(); throw Refusal.expired }
    }
    public func append(sequence: Int, utterance: String, end: Int, data: Data, sha256: String) throws {
        try check()
        try queue.append(sequence: sequence, utterance: utterance, end: end, data: data, sha256: sha256)
        do { try pump() } catch { close(); emit(.unavailable); throw error }
    }
    private func pump() throws {
        guard !closed, !paused else { return }
        try check()
        while tickets.count < 8, let next = queue.next() {
            if !active { try activate(); active = true }
            let id = UUID(), generation = epoch, end = queue.submittedBytes + next.data.count
            tickets.append(Ticket(id: id, end: end))
            try device.schedule(next.data) { [weak self] in
                // Never stop/unschedule an Apple node inside its audio callback.
                DispatchQueue.main.async { self?.completed(id, generation: generation) }
            }
            try queue.submitted(next.data.count)
            try device.start()
        }
    }
    private func completed(_ id: UUID, generation: UUID) {
        guard !closed, epoch == generation, let index = tickets.firstIndex(where: { $0.id == id }) else { return }
        do {
            try check(); tickets[index].complete = true
            var end: Int?
            while tickets.first?.complete == true { end = tickets.removeFirst().end }
            if let end {
                let changed = try queue.advance(to: end)
                if !reportedPlaying { reportedPlaying = true; emit(.playing) }
                guard !closed, epoch == generation else { return }
                if !changed.isEmpty { emit(.progress(changed)) }
            }
            guard !closed, epoch == generation else { return }
            try pump()
            if tickets.isEmpty && queue.queuedBytes == 0 {
                device.pause(); release(); reportedPlaying = false; emit(.quiet)
            }
        } catch { close(); emit(.unavailable) }
    }
    private func release() { if active { active = false; deactivate() } }
    public func pause() throws { try check(); paused = true; device.pause(); release(); emit(.paused) }
    public func resume() throws {
        try check(); paused = false
        do {
            if !tickets.isEmpty { if !active { try activate(); active = true }; try device.start() }
            try pump()
        } catch { close(); emit(.unavailable); throw error }
    }
    public func flush() throws {
        try check(); epoch = UUID(); tickets.removeAll(); queue.flush(); device.stop()
        release(); reportedPlaying = false; emit(.quiet)
    }
    public func close() {
        guard !closed else { return }
        closed = true; epoch = UUID(); deadline?.cancel(); deadline = nil
        tickets.removeAll(); queue.flush(); device.stop(); release(); emit(.closed)
    }
    deinit {
        deadline?.cancel()
        let output = device, release = active ? deactivate : nil
        DispatchQueue.main.async { output.stop(); release?() }
    }
}
