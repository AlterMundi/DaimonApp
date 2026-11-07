import Foundation

/// Port of Android's BeaconSynth: six phase-continuous sine carriers. All state
/// belongs to one serial audio owner; no device, session, observer or provider.
@MainActor final class BeaconSynth {
    enum Refusal: Error { case invalidConfiguration, invalidTransition, invalidWeights, invalidLevel, invalidWindow }
    static let tones = 6
    private let rate: Int
    private let frequencies: [Double]
    private let pulses: [Double]
    private let depth: Double
    private var phase = Array(repeating:0.0,count:6)
    private var pulsePhase = Array(repeating:0.0,count:6)
    private var weight = Array(repeating:0.0,count:6)
    private var target = Array(repeating:0.0,count:6)
    private var step = Array(repeating:0.0,count:6)
    private var weightFrames = 0, gainFrames = 0
    private var gain = 0.0, targetGain = 0.0, gainStep = 0.0
    private let tau = 2 * Double.pi

    init(sampleRate: Int = 24000, frequencies: [Double], pulses: [Double], depth: Double) throws {
        guard (24000...96000).contains(sampleRate), frequencies.count == 6, pulses.count == 6,
              Self.finite(depth,0,0.5), frequencies.allSatisfy({ Self.finite($0,20,16384) }),
              pulses.allSatisfy({ Self.finite($0,0,64) }) else { throw Refusal.invalidConfiguration }
        rate = sampleRate; self.frequencies = frequencies; self.pulses = pulses; self.depth = depth
    }
    private static func finite(_ value: Double, _ minimum: Double, _ maximum: Double) -> Bool {
        value.isFinite && value >= minimum && value <= maximum
    }
    private func frames(_ milliseconds: Int) throws -> Int {
        guard (0...2000).contains(milliseconds) else { throw Refusal.invalidTransition }
        return rate * milliseconds / 1000
    }
    func weights(_ next: [Double], milliseconds: Int) throws {
        let frames = try frames(milliseconds)
        guard next.count == 6 else { throw Refusal.invalidWeights }
        var sum = 0.0
        for i in 0..<6 {
            guard Self.finite(next[i],0,1), next[i] == 0 || frequencies[i] < Double(rate) * 0.45 else { throw Refusal.invalidWeights }
            sum += next[i]
        }
        guard sum <= 1 + 1e-9 else { throw Refusal.invalidWeights }
        guard next != target else { return } // A refresh cannot restart the envelope.
        weightFrames = frames
        for i in 0..<6 {
            target[i] = next[i]; step[i] = frames == 0 ? 0 : (next[i]-weight[i])/Double(frames)
            if frames == 0 { weight[i] = next[i] }
        }
    }
    func level(_ next: Double, milliseconds: Int) throws {
        let frames = try frames(milliseconds)
        guard Self.finite(next,0,0.8) else { throw Refusal.invalidLevel }
        guard next != targetGain else { return }
        targetGain = next; gainFrames = frames; gainStep = frames == 0 ? 0 : (next-gain)/Double(frames)
        if frames == 0 { gain = next }
    }
    var silent: Bool {
        if gainFrames == 0 && gain == 0 { return true }
        return weightFrames == 0 && weight.allSatisfy { $0 == 0 }
    }
    func render(into output: inout [Int16], offset: Int = 0, count: Int) throws {
        guard offset >= 0, count >= 0, count <= output.count, offset <= output.count-count else { throw Refusal.invalidWindow }
        for n in offset..<(offset+count) {
            if weightFrames > 0 {
                weightFrames -= 1
                for i in 0..<6 { weight[i] = weightFrames == 0 ? target[i] : weight[i]+step[i] }
            }
            if gainFrames > 0 { gainFrames -= 1; gain = gainFrames == 0 ? targetGain : gain+gainStep }
            var value = 0.0
            for i in 0..<6 {
                let breath = pulses[i] == 0 ? 1 : 1-depth+depth*sin(pulsePhase[i])
                value += weight[i]*sin(phase[i])*breath
                phase[i] += tau*frequencies[i]/Double(rate)
                pulsePhase[i] += tau*pulses[i]/Double(rate)
                if phase[i] >= tau { phase[i] -= tau }
                if pulsePhase[i] >= tau { pulsePhase[i] -= tau }
            }
            // Java Math.round rounds half toward positive infinity. Preserve the
            // Android PCM16 quantization rather than Swift's default tie rule.
            output[n] = Int16(floor(max(-1,min(1,value*gain))*32767+0.5))
        }
    }
}
