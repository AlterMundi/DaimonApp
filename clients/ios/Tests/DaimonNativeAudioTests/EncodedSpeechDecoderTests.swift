import Foundation
import XCTest
@testable import DaimonNativeAudio

private final class PCMCollector: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    func append(_ next: Data) { lock.lock(); defer { lock.unlock() }; data.append(next) }
    func snapshot() -> Data { lock.lock(); defer { lock.unlock() }; return data }
}

final class EncodedSpeechDecoderTests: XCTestCase {
    private func fixture() throws -> Data {
        var root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        for _ in 0..<4 { root.deleteLastPathComponent() }
        return try Data(contentsOf: root.appendingPathComponent("clients/android/app/src/androidTest/assets/speech-prefix.mp3"))
    }
    private func append(_ source: VerifiedEncodedAudioSource, _ data: Data, from: Int = 0) throws {
        var sequence = from
        for start in stride(from: 0, to: data.count, by: 32768) {
            let chunk = data.subdata(in: start..<min(data.count, start + 32768))
            try source.append(sequence: sequence, data: chunk, sha256: PCMPlaybackQueue.digest(chunk))
            sequence += 1
        }
    }
    private func complete(_ data: Data) throws -> VerifiedEncodedAudioSource {
        let source = try VerifiedEncodedAudioSource()
        try append(source, data); try source.finish(bytes: data.count, sha256: PCMPlaybackQueue.digest(data))
        return source
    }
    private func decode(_ data: Data, readSize: Int) throws -> Data {
        let source = try complete(data), collected = PCMCollector()
        let decoder = try EncodedSpeechDecoder { part in
            XCTAssertFalse(part.isEmpty); XCTAssertLessThanOrEqual(part.count, 8192)
            XCTAssertTrue(part.count.isMultiple(of: 2)); collected.append(part)
        }
        try decoder.run(source, readSize: readSize)
        XCTAssertTrue(source.isClosed, "Decoded compressed bytes must not remain retained")
        let output = collected.snapshot()
        XCTAssertEqual(output.count, decoder.decodedFrames * 2)
        return output
    }
    func testRealMP3PacketSplitsPreserveTheCompleteDecodedPCM() throws {
        let encoded = try fixture()
        let whole = try decode(encoded, readSize: 32768)
        let fragmented = try decode(encoded, readSize: 137)
        XCTAssertEqual(whole, fragmented, "Parser packet boundaries must not duplicate or drop PCM")
        XCTAssertGreaterThan(whole.count, 24000 * 2 * 10)
        XCTAssertLessThan(whole.count, 24000 * 2 * 14)
        XCTAssertTrue(whole.contains { $0 != 0 }, "A synthetic non-silent fixture must actually decode")
    }
    func testVerifiedPrefixDecodesBeforeTerminalWithoutTreatingMissingBytesAsEOF() throws {
        let encoded = try fixture(), source = try VerifiedEncodedAudioSource()
        let first = encoded.prefix(32768), collected = PCMCollector()
        try source.append(sequence: 0, data: Data(first), sha256: PCMPlaybackQueue.digest(Data(first)))
        let prefix = DispatchSemaphore(value: 0), done = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            defer { done.signal() }
            do {
                let decoder = try EncodedSpeechDecoder { data in collected.append(data); prefix.signal() }
                try decoder.run(source)
            } catch { XCTFail("Verified progressive input failed: \(error)") }
        }
        XCTAssertEqual(prefix.wait(timeout: .now() + 3), .success)
        XCTAssertNil(source.size)
        XCTAssertEqual(done.wait(timeout: .now() + 0.02), .timedOut)
        try append(source, encoded.subdata(in: 32768..<encoded.count), from: 1)
        try source.finish(bytes: encoded.count, sha256: PCMPlaybackQueue.digest(encoded))
        XCTAssertEqual(done.wait(timeout: .now() + 3), .success)
        XCTAssertEqual(collected.snapshot(), try decode(encoded, readSize: 32768))
    }
    func testInvalidContainerAndRetiredIntegrityCannotProducePCM() throws {
        var output = 0
        let invalid = try complete(Data("not an MP3 stream".utf8))
        let decoder = try EncodedSpeechDecoder { output += $0.count }
        XCTAssertThrowsError(try decoder.run(invalid)); XCTAssertEqual(output, 0)
        let retired = try VerifiedEncodedAudioSource()
        XCTAssertThrowsError(try retired.append(sequence: 0, data: Data([1]), sha256: String(repeating: "0", count: 64)))
        let other = try EncodedSpeechDecoder { output += $0.count }
        XCTAssertThrowsError(try other.run(retired)); XCTAssertEqual(output, 0)
    }
    func testPCMCapacityIsFiniteAndNoDecoderCanReplayAConsumedSource() throws {
        let encoded = try fixture(), source = try complete(encoded)
        var output = 0
        let decoder = try EncodedSpeechDecoder(maximumPCMFrames: 1) { output += $0.count }
        XCTAssertThrowsError(try decoder.run(source)); XCTAssertEqual(output, 0)
        XCTAssertTrue(source.isClosed)
        let fresh = try complete(encoded); defer { fresh.close() }
        XCTAssertThrowsError(try decoder.run(fresh)); XCTAssertEqual(output, 0)
        XCTAssertThrowsError(try EncodedSpeechDecoder(maximumPCMFrames: 24000 * 600 + 1, emit: { _ in }))
    }
    func testConsumerCloseOrRefusalStopsFurtherDecodeWithoutRetry() throws {
        let encoded = try fixture(), source = try complete(encoded)
        var calls = 0
        let decoder = try EncodedSpeechDecoder { _ in calls += 1; source.close() }
        XCTAssertThrowsError(try decoder.run(source)); XCTAssertEqual(calls, 1)
        let otherSource = try complete(encoded)
        let other = try EncodedSpeechDecoder { _ in throw PCMPlaybackQueue.Refusal.invalidSpan }
        XCTAssertThrowsError(try other.run(otherSource)); XCTAssertTrue(otherSource.isClosed)
    }
}
