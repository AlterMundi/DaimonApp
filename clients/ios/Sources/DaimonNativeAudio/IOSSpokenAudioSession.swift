#if os(iOS)
import AVFAudio
import Foundation
import UIKit

@MainActor private final class IOSSessionDevice: AudioSessionDevice {
    private let session = AVAudioSession.sharedInstance()
    func activate(mode: AudioSessionMode) throws {
        switch mode {
        case .spokenOutput: try session.setCategory(.playback, mode:.spokenAudio, options:[.duckOthers])
        case .duplexVoice: try session.setCategory(.playAndRecord, mode:.voiceChat, options:[.defaultToSpeaker,.allowBluetooth,.duckOthers])
        }
        try session.setActive(true)
    }
    func deactivate() throws { try session.setActive(false, options: [.notifyOthersOnDeactivation]) }
}

/// The app owns one instance. Explicit foreground capture freezes duplex mode;
/// output alone uses spoken mode. Neither grants microphone permission, background
/// audio, automatic resumption or another login/store.
@MainActor public final class IOSSpokenAudioSession {
    private let ownership = AudioSessionOwnership(device: IOSSessionDevice(), supportsCapture:true)
    private var observers: [NSObjectProtocol] = []
    private var outputs: [UUID: WeakOutput] = [:]
    private var beacon: WeakBeacon?
    private var foreground = true
    private var cancelling = false
    private var capture: (id: UUID, deadline: DispatchWorkItem, cancel: () -> Void)?
    private var captureEnding = false
    public var releaseUnconfirmed: Bool { ownership.unconfirmedRelease != nil }
    public var unconfirmedReleaseID: UUID? { ownership.unconfirmedRelease }

    public init() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: nil) { [weak self] note in
                let began = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber)?.uintValue == AVAudioSession.InterruptionType.began.rawValue
                if began { Task { @MainActor in self?.cancelOutputs() } }
            })
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
            object: nil, queue: nil) { [weak self] note in
                let raw = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? NSNumber)?.uintValue ?? 0
                let reason = AVAudioSession.RouteChangeReason(rawValue: raw)
                if reason == .oldDeviceUnavailable || reason == .noSuitableRouteForCategory
                    || reason == .override || reason == .routeConfigurationChange {
                    Task { @MainActor in self?.cancelOutputs() }
                }
            })
        observers.append(center.addObserver(forName: UIApplication.didEnterBackgroundNotification,
            object: nil, queue: nil) { [weak self] _ in Task { @MainActor in self?.leaveForeground() } })
        observers.append(center.addObserver(forName: UIApplication.didBecomeActiveNotification,
            object: nil, queue: nil) { [weak self] _ in Task { @MainActor in self?.enterForeground() } })
    }

    public func makeOutput(seconds: Int = 300, emit: @escaping (PCMPlaybackDriver.Event) -> Void) throws -> PCMPlaybackDriver {
        reapOutputs()
        guard foreground, !cancelling, !captureEnding, UIApplication.shared.applicationState == .active,
              outputs.count + (beacon == nil ? 0 : 1) < 2, !releaseUnconfirmed else { throw AudioSessionOwnership.Refusal.unavailable }
        let owner = UUID()
        // One small weak link lets this session cancel exactly its driver without
        // retaining a driver->session->driver cycle or a replaceable global sink.
        let link = WeakOutput()
        outputs[owner] = link
        do {
            let driver = try PCMPlaybackDriver(seconds: seconds, activate: { [self, link] in
                guard foreground, !cancelling, !captureEnding, UIApplication.shared.applicationState == .active,
                      outputs[owner] === link else { throw AudioSessionOwnership.Refusal.unavailable }
                try ownership.acquire(owner, mode: ownership.mode ?? .spokenOutput) { [link] in link.driver?.close() }
            }, deactivate: { [self] in
                if !ownership.release(owner) { emit(.unavailable) }
            }, emit: { [weak self] event in
                if case .closed = event { self?.outputs.removeValue(forKey: owner) }
                emit(event)
            })
            link.driver = driver; link.preparing = false
            guard foreground, outputs[owner] === link else { driver.close(); throw AudioSessionOwnership.Refusal.unavailable }
            return driver
        } catch { outputs.removeValue(forKey: owner); throw error }
    }
    /// Called before the selected page requests microphone permission. This is
    /// session ownership only; WebKit/OS still prompt and own actual recording.
    public func beginCapture(_ id: UUID, cancelled: @escaping () -> Void) throws {
        guard foreground, !cancelling, capture == nil,
              UIApplication.shared.applicationState == .active else { throw AudioSessionOwnership.Refusal.unavailable }
        try ownership.acquire(id,mode:.duplexVoice,cancelled:cancelled)
        let deadline = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                guard let self, self.capture?.id == id else { return }
                self.captureEnding = true; cancelled()
            }
        }
        capture = (id,deadline,cancelled)
        DispatchQueue.main.asyncAfter(deadline:.now()+600,execute:deadline)
    }
    public func endCapture(_ id: UUID) {
        guard capture?.id == id else { return }
        capture?.deadline.cancel(); capture = nil; captureEnding = false
        _ = ownership.release(id)
    }
    private func reapOutputs() {
        outputs = outputs.filter { $0.value.preparing || $0.value.driver != nil }
        if beacon?.preparing == false && beacon?.driver == nil { beacon = nil }
    }
    /// The host must receive an explicit foreground Beacon selection. Creating
    /// this prepared owner neither starts sound nor changes the app's flags.
    public func makeBeacon(emit: @escaping (BeaconPlaybackDriver.Event) -> Void) throws -> BeaconPlaybackDriver {
        reapOutputs()
        guard foreground, !cancelling, !captureEnding, UIApplication.shared.applicationState == .active,
              outputs.count < 2, beacon == nil, !releaseUnconfirmed else { throw AudioSessionOwnership.Refusal.unavailable }
        let owner = UUID(), link = WeakBeacon(); beacon = link
        do {
            let driver = try BeaconPlaybackDriver(activate:{ [self, link] in
                guard foreground, !cancelling, !captureEnding, UIApplication.shared.applicationState == .active,
                      beacon === link else { throw AudioSessionOwnership.Refusal.unavailable }
                try ownership.acquire(owner, mode:ownership.mode ?? .spokenOutput) { [link] in link.driver?.close() }
            },deactivate:{ [self] in
                if !ownership.release(owner) { emit(.unavailable) }
            },emit:{ [weak self] event in
                if case .closed = event, self?.beacon === link { self?.beacon = nil }
                emit(event)
            })
            link.driver = driver; link.preparing = false
            guard foreground, beacon === link else { driver.close(); throw AudioSessionOwnership.Refusal.unavailable }
            return driver
        } catch { if beacon === link { beacon = nil }; throw error }
    }
    private func cancelOutputs() {
        guard !cancelling else { return }
        cancelling = true
        if let old = capture {
            captureEnding = true; old.deadline.cancel(); old.cancel()
        }
        let oldBeacon = beacon; beacon = nil
        oldBeacon?.driver?.close()
        let snapshot = outputs; outputs.removeAll()
        for link in snapshot.values { link.driver?.close() }
        if capture == nil { ownership.cancelOwned() }
        cancelling = false
    }
    public func leaveForeground() { foreground = false; cancelOutputs() }
    public func enterForeground() { foreground = UIApplication.shared.applicationState == .active }
    /// Explicit user recovery only; never called by notification/refresh/close.
    @discardableResult public func recoverRelease(owner: UUID) -> Bool {
        return ownership.recoverRelease(owner)
    }
    deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }
}

@MainActor private final class WeakBeacon { weak var driver: BeaconPlaybackDriver?; var preparing = true }
@MainActor private final class WeakOutput { weak var driver: PCMPlaybackDriver?; var preparing = true }
#endif
