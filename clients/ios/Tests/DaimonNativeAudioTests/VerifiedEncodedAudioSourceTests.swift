import Foundation
import XCTest
@testable import DaimonNativeAudio

final class VerifiedEncodedAudioSourceTests: XCTestCase {
    private let helloDigest = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    private func append(_ source: VerifiedEncodedAudioSource, _ sequence: Int, _ text: String) throws {
        let data = Data(text.utf8)
        try source.append(sequence: sequence, data: data, sha256: PCMPlaybackQueue.digest(data))
    }
    func testPrefixAndCrossChunkReadsOnlyExposeVerifiedTerminalEOF() throws {
        let source = try VerifiedEncodedAudioSource(maximum: 32)
        defer { source.close() }
        try append(source, 0, "hel")
        XCTAssertNil(source.size)
        XCTAssertEqual(try source.read(at: 0, length: 5), Data("hel".utf8))
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            defer { done.signal() }
            do { XCTAssertEqual(try source.read(at: 3, length: 2), Data("lo".utf8)) }
            catch { XCTFail("An incomplete prefix became a decoder error: \(error)") }
        }
        XCTAssertEqual(done.wait(timeout: .now() + 0.02), .timedOut, "Missing bytes cannot be terminal EOF")
        try append(source, 1, "lo")
        XCTAssertEqual(done.wait(timeout: .now() + 1), .success)
        try source.finish(bytes: 5, sha256: helloDigest)
        XCTAssertEqual(source.size, 5)
        XCTAssertEqual(try source.read(at: 2, length: 3), Data("llo".utf8))
        XCTAssertNil(try source.read(at: 5, length: 1))
    }
    func testInvalidSequenceHashAndCapacityRetireTheSource() throws {
        for fault in 0..<3 {
            let source = try VerifiedEncodedAudioSource(maximum: 2)
            let data = Data((fault == 2 ? "abc" : "a").utf8)
            XCTAssertThrowsError(try source.append(sequence: fault == 0 ? 1 : 0, data: data,
                sha256: fault == 1 ? String(repeating: "0", count: 64) : PCMPlaybackQueue.digest(data)))
            XCTAssertNil(source.size)
            XCTAssertThrowsError(try source.read(at: 0, length: 1))
            XCTAssertThrowsError(try append(source, 0, "a"), "Failure cannot reset the source identity")
        }
    }
    func testTerminalLengthAndWholeDigestMustBothMatch() throws {
        for fault in 0..<2 {
            let source = try VerifiedEncodedAudioSource(maximum: 8)
            try append(source, 0, "hello")
            XCTAssertThrowsError(try source.finish(bytes: fault == 0 ? 4 : 5,
                sha256: fault == 0 ? helloDigest : String(repeating: "0", count: 64)))
            XCTAssertNil(source.size)
            XCTAssertThrowsError(try source.read(at: 5, length: 1), "Bad termination cannot expose successful EOF")
        }
        let source = try VerifiedEncodedAudioSource(maximum: 8)
        try append(source, 0, "hello"); try source.finish(bytes: 5, sha256: helloDigest)
        XCTAssertThrowsError(try append(source, 1, "!"))
        XCTAssertNil(source.size)
    }
    func testCloseWakesAWaitingDecoderWithoutASecondReadOrRetry() throws {
        let source = try VerifiedEncodedAudioSource()
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            defer { done.signal() }
            XCTAssertThrowsError(try source.read(at: 0, length: 1))
        }
        source.close()
        XCTAssertEqual(done.wait(timeout: .now() + 1), .success)
        XCTAssertThrowsError(try source.read(at: 0, length: 1))
    }
    func testCallerInputAndReturnedDataCannotChangeRetainedBytes() throws {
        let source = try VerifiedEncodedAudioSource(maximum: 8)
        var input = Data("hello".utf8)
        try source.append(sequence: 0, data: input, sha256: helloDigest)
        input[0] = 0
        var output = try XCTUnwrap(source.read(at: 0, length: 5)); output[0] = 1
        try source.finish(bytes: 5, sha256: helloDigest)
        XCTAssertEqual(try source.read(at: 0, length: 5), Data("hello".utf8))
    }
    func testStalledReadsFailWithinTheExistingDecoderWaitBound() throws {
        let source = try VerifiedEncodedAudioSource(maximum: 8, waitSeconds: 0.02, lifetimeSeconds: 0.1)
        let start = ProcessInfo.processInfo.systemUptime
        XCTAssertThrowsError(try source.read(at: 0, length: 1))
        XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - start, 1)
        XCTAssertNil(source.size)
        XCTAssertThrowsError(try append(source, 0, "a"))
    }
    func testConstructorChunkAndReadBoundsDoNotAllocateUnboundedState() throws {
        XCTAssertThrowsError(try VerifiedEncodedAudioSource(maximum: 0))
        XCTAssertThrowsError(try VerifiedEncodedAudioSource(maximum: VerifiedEncodedAudioSource.maximumBytes + 1))
        XCTAssertThrowsError(try VerifiedEncodedAudioSource(waitSeconds: .infinity))
        XCTAssertThrowsError(try VerifiedEncodedAudioSource(lifetimeSeconds: 146))
        let source = try VerifiedEncodedAudioSource()
        let data = Data(repeating: 0, count: VerifiedEncodedAudioSource.maximumChunkBytes + 1)
        XCTAssertThrowsError(try source.append(sequence: 0, data: data, sha256: PCMPlaybackQueue.digest(data)))
        let other = try VerifiedEncodedAudioSource()
        XCTAssertThrowsError(try other.read(at: Int.max, length: 1))
        let empty = try VerifiedEncodedAudioSource()
        XCTAssertThrowsError(try empty.finish(bytes: 0, sha256: PCMPlaybackQueue.digest(Data())))
    }
}
