import Foundation
import XCTest
@testable import DaimonNativeAudio

final class BeaconSynthTests: XCTestCase {
    private let frequencies = [40.4,80.8,121.2,161.6,282.8,444.4]
    @MainActor private func synth() throws -> BeaconSynth {
        try BeaconSynth(frequencies:frequencies,pulses:Array(repeating:0,count:6),depth:0)
    }
    @MainActor private func render(_ synth: BeaconSynth, _ output: inout [Int16]) throws {
        let count = output.count
        try synth.render(into:&output,count:count)
    }
    private func amplitude(_ samples: [Int16], hz: Double) -> Double {
        var sine = 0.0, cosine = 0.0
        for (i,sample) in samples.enumerated() {
            sine += Double(sample)/32767 * sin(2*Double.pi*hz*Double(i)/24000)
            cosine += Double(sample)/32767 * cos(2*Double.pi*hz*Double(i)/24000)
        }
        return 2*hypot(sine,cosine)/Double(samples.count)
    }
    @MainActor func testExactSixCarriersAndNormalizedMixWithoutInventedPartials() async throws {
        let single = try synth(), mix = try synth()
        try single.weights([1,0,0,0,0,0],milliseconds:0); try single.level(0.6,milliseconds:0)
        try mix.weights(Array(repeating:1.0/6,count:6),milliseconds:0); try mix.level(0.6,milliseconds:0)
        var a = Array(repeating:Int16(0),count:120000), b = a
        try render(single,&a); try render(mix,&b)
        XCTAssertEqual(amplitude(a,hz:40.4),0.6,accuracy:0.0001)
        for hz in [18.0,65,80.8,121.2,161.6,202,282.8,444.4] { XCTAssertLessThan(amplitude(a,hz:hz),0.0001) }
        for hz in frequencies { XCTAssertEqual(amplitude(b,hz:hz),0.1,accuracy:0.0001) }
        XCTAssertTrue(b.allSatisfy { abs(Int($0)) <= Int(ceil(0.6*32767)) })
    }
    @MainActor func testChunkingAndRepeatedControlsCannotRestartPhasesOrRamps() async throws {
        let whole = try synth(), chunks = try synth(), first = [1.0,0,0,0,0,0]
        try whole.weights(first,milliseconds:1000); try chunks.weights(first,milliseconds:1000)
        try whole.level(0.6,milliseconds:120); try chunks.level(0.6,milliseconds:120)
        var a = Array(repeating:Int16(0),count:48000), b = a
        try render(whole,&a)
        for offset in stride(from:0,to:b.count,by:137) {
            try chunks.weights(first,milliseconds:1000); try chunks.level(0.6,milliseconds:120)
            let count = min(137,b.count-offset)
            try chunks.render(into:&b,offset:offset,count:count)
        }
        XCTAssertEqual(a,b)
    }
    @MainActor func testBreathingIsOnlyTheSelectedHarmonicAmplitudeEnvelope() async throws {
        let value = try BeaconSynth(frequencies:frequencies,pulses:[0.25,0.5,0.75,1,1.75,2.75],depth:0.25)
        try value.weights([1,0,0,0,0,0],milliseconds:0); try value.level(0.6,milliseconds:0)
        var samples = Array(repeating:Int16(0),count:24000); try render(value,&samples)
        for (i,sample) in samples.enumerated() {
            let time = Double(i)/24000
            let expected = floor(32767*0.6*sin(2*Double.pi*40.4*time)*(0.75+0.25*sin(2*Double.pi*0.25*time))+0.5)
            XCTAssertEqual(Double(sample),expected,accuracy:1)
        }
    }
    @MainActor func testRetargetingFromCurrentValuesSettlesToExactSilence() async throws {
        let value = try synth(); try value.weights([1,0,0,0,0,0],milliseconds:0); try value.level(0.6,milliseconds:0)
        var samples = Array(repeating:Int16(0),count:2400); try render(value,&samples)
        for n in 0..<10 {
            try value.weights(n.isMultiple(of:2) ? [0,1,0,0,0,0] : [1,0,0,0,0,0],milliseconds:1000)
            try render(value,&samples)
            XCTAssertTrue(samples.allSatisfy { abs(Int($0)) <= Int(ceil(0.6*32767)) })
        }
        try value.level(0,milliseconds:350)
        var tail = Array(repeating:Int16(1),count:9000); try render(value,&tail)
        XCTAssertTrue(tail[8400...].allSatisfy { $0 == 0 }); XCTAssertTrue(value.silent)
    }
    @MainActor func testInvalidUpdatesAreAtomicAndInputArraysCannotMutateTheOwner() async throws {
        var owned = frequencies
        let valid = try BeaconSynth(frequencies:owned,pulses:Array(repeating:0,count:6),depth:0), reference = try synth()
        owned[0] = 1000
        var first = [1.0,0,0,0,0,0]
        try valid.weights(first,milliseconds:0); try reference.weights(first,milliseconds:0)
        try valid.level(0.6,milliseconds:0); try reference.level(0.6,milliseconds:0); first[0] = 0
        XCTAssertThrowsError(try valid.weights([1,1,0,0,0,0],milliseconds:100))
        XCTAssertThrowsError(try valid.level(.nan,milliseconds:100))
        XCTAssertThrowsError(try valid.weights(Array(repeating:0,count:6),milliseconds:2001))
        var a = Array(repeating:Int16(0),count:1000), b = a
        XCTAssertThrowsError(try valid.render(into:&a,offset:1,count:1000))
        try render(valid,&a); try render(reference,&b); XCTAssertEqual(a,b)
        let aliased = try BeaconSynth(frequencies:[16384,80.8,121.2,161.6,282.8,444.4],pulses:Array(repeating:0,count:6),depth:0)
        XCTAssertThrowsError(try aliased.weights([1,0,0,0,0,0],milliseconds:0))
        XCTAssertThrowsError(try BeaconSynth(sampleRate:23999,frequencies:frequencies,pulses:Array(repeating:0,count:6),depth:0))
    }
    @MainActor func testSelectedPCMMatchesTheExistingAndroidImplementation() async throws {
        let value = try BeaconSynth(frequencies:frequencies,pulses:[0.25,0.5,0.75,1,1.75,2.75],depth:0.25)
        let first = [0.3,0.2,0.15,0.15,0.1,0.1], next = [0.0,0.25,0.25,0.25,0.125,0.125]
        try value.weights(first,milliseconds:1000); try value.level(0.6,milliseconds:120)
        var bytes = Data(), block = Array(repeating:Int16(0),count:960)
        for n in 0..<50 {
            if n == 16 { try value.weights(next,milliseconds:350); try value.level(0.42,milliseconds:80) }
            if n == 32 { try value.weights(next,milliseconds:350); try value.level(0.42,milliseconds:80) }
            if n == 40 { try value.level(0,milliseconds:350) }
            try render(value,&block)
            for sample in block {
                let bits = UInt16(bitPattern:sample)
                bytes.append(UInt8(truncatingIfNeeded:bits)); bytes.append(UInt8(truncatingIfNeeded:bits>>8))
            }
        }
        // Generated by the existing Android BeaconSynth, not another Swift path.
        XCTAssertEqual(PCMPlaybackQueue.digest(bytes),"ce5dba3a698bc0c2629b6b097b79ef12cbce1dc25a8485e25a494538472be8e0")
    }

}
