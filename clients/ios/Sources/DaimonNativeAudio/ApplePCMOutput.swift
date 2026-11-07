import AVFAudio
import Foundation

/// AVAudioEngine ownership only. The app owns AVAudioSession, capture, shared
/// login and lifecycle policy; constructing this graph requests none of those.
final class ApplePCMOutput: PCMOutputDevice {
    enum Refusal: Error { case invalidPCM, bufferUnavailable, offlinePlayback }
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var prepared = false

    static func buffer(_ data: Data) throws -> AVAudioPCMBuffer {
        guard (2...32768).contains(data.count), data.count.isMultiple(of: 2),
              let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(data.count / 2)),
              let channel = buffer.floatChannelData?[0] else { throw Refusal.invalidPCM }
        buffer.frameLength = buffer.frameCapacity
        data.withUnsafeBytes { raw in
            let bytes = raw.bindMemory(to: UInt8.self)
            for n in 0..<Int(buffer.frameLength) {
                let bits = UInt16(bytes[2 * n]) | UInt16(bytes[2 * n + 1]) << 8
                channel[n] = Float(Int16(bitPattern: bits)) / 32768
            }
        }
        return buffer
    }
    func prepare() throws {
        guard !prepared else { return }
        guard let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1) else { throw Refusal.bufferUnavailable }
        engine.attach(player); engine.connect(player, to: engine.mainMixerNode, format: format)
        engine.prepare(); prepared = true
    }
    func schedule(_ data: Data, completion: @escaping () -> Void) throws {
        guard !engine.isInManualRenderingMode else { throw Refusal.offlinePlayback }
        let pcm = try Self.buffer(data)
        player.scheduleBuffer(pcm, completionCallbackType: .dataPlayedBack) { type in
            if type == .dataPlayedBack { completion() }
        }
    }
    func start() throws { if !engine.isRunning { try engine.start() }; if !player.isPlaying { player.play() } }
    func pause() { player.pause(); engine.pause() }
    func stop() { player.stop(); engine.stop() }
    deinit { player.stop(); engine.stop() }
}
