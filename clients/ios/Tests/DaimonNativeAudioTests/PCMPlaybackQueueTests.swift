import Foundation
import XCTest
@testable import DaimonNativeAudio

final class PCMPlaybackQueueTests: XCTestCase {
    private let first = UUID().uuidString.lowercased()
    private let second = UUID().uuidString.lowercased()
    private func append(_ queue: PCMPlaybackQueue, _ sequence: Int, _ id: String,
                        _ end: Int, _ size: Int) throws {
        let data = Data(repeating: 0, count: size)
        try queue.append(sequence: sequence, utterance: id, end: end,
                         data: data, sha256: PCMPlaybackQueue.digest(data))
    }
    func testPartialSubmissionNeverBecomesPlayback() throws {
        let q = try PCMPlaybackQueue()
        try append(q, 0, first, 8, 8); try append(q, 1, second, 4, 4)
        try q.submitted(4)
        XCTAssertEqual(q.queuedBytes, 12)
        XCTAssertThrowsError(try q.advance(to: 6))
        XCTAssertEqual(try q.advance(to: 2), [first: 2])
        XCTAssertEqual(try q.advance(to: 2), [:])
        XCTAssertEqual(q.next()?.data.count, 4)
        try q.submitted(4); try q.submitted(4)
        XCTAssertEqual(try q.advance(to: 10), [first: 8, second: 2])
        XCTAssertEqual(try q.advance(to: 12), [second: 4])
        XCTAssertNil(q.next()); XCTAssertEqual(q.queuedBytes, 0)
    }
    func testSourceOffsetsAndRetiredIdentitySurviveFlush() throws {
        let q = try PCMPlaybackQueue()
        try append(q, 0, first, 4, 4); try q.submitted(4); _ = try q.advance(to: 4)
        try append(q, 1, first, 8, 4); try q.submitted(4)
        XCTAssertEqual(try q.advance(to: 6), [first: 6])
        q.flush()
        XCTAssertNil(q.next()); XCTAssertEqual(q.queuedBytes, 0)
        XCTAssertThrowsError(try append(q, 2, first, 12, 4))
        try append(q, 2, second, 4, 4); try q.submitted(4)
        XCTAssertEqual(try q.advance(to: 2), [second: 2])
        XCTAssertEqual(q.lifetimeBytes, 12)
    }
    func testMalformedAdmissionAndPositionsAreAtomic() throws {
        let q = try PCMPlaybackQueue()
        XCTAssertThrowsError(try append(q, 1, first, 4, 4))
        XCTAssertThrowsError(try append(q, 0, first, 4, 3))
        XCTAssertThrowsError(try append(q, 0, first, 8, 4))
        XCTAssertThrowsError(try append(q, 0, "not-a-uuid", 4, 4))
        XCTAssertThrowsError(try q.append(sequence: 0, utterance: first, end: 4,
                                        data: Data(repeating: 0, count: 4), sha256: String(repeating: "0", count: 64)))
        XCTAssertEqual(q.sequence, 0); XCTAssertEqual(q.lifetimeBytes, 0)
        try append(q, 0, first, 4, 4)
        XCTAssertThrowsError(try q.submitted(-2)); XCTAssertThrowsError(try q.submitted(3))
        XCTAssertThrowsError(try q.submitted(6)); XCTAssertEqual(q.submittedBytes, 0)
        try q.submitted(4); _ = try q.advance(to: 4)
        XCTAssertThrowsError(try q.advance(to: 2)); XCTAssertEqual(q.playedBytes, 4)
    }
    func testQueueAndSourceCountBounds() throws {
        let q = try PCMPlaybackQueue()
        for n in 0..<45 { try append(q, n, first, (n + 1) * 32000, 32000) }
        XCTAssertEqual(q.queuedBytes, PCMPlaybackQueue.maximumQueuedBytes)
        XCTAssertThrowsError(try append(q, 45, first, 1440002, 2))
        q.flush()
        for n in 0..<127 { try append(q, 45 + n, UUID().uuidString.lowercased(), 2, 2) }
        XCTAssertThrowsError(try append(q, 172, UUID().uuidString.lowercased(), 2, 2))
        let small = try PCMPlaybackQueue()
        for n in 0..<512 { try append(small, n, first, (n + 1) * 2, 2) }
        XCTAssertThrowsError(try append(small, 512, first, 1026, 2))
    }
    func testTenMinuteLifetimeDoesNotResetAfterFlush() throws {
        XCTAssertThrowsError(try PCMPlaybackQueue(seconds: 299))
        XCTAssertThrowsError(try PCMPlaybackQueue(seconds: 601))
        let q = try PCMPlaybackQueue(seconds: 600)
        var id = first, source = 0, played = 0
        for n in 0..<900 {
            if n == 450 { q.flush(); id = second; source = 0; played = 0 }
            source += 32000; try append(q, n, id, source, 32000)
            try q.submitted(32000); played += 32000; _ = try q.advance(to: played)
            XCTAssertEqual(q.queuedBytes, 0)
        }
        XCTAssertThrowsError(try append(q, 900, id, source + 2, 2))
        XCTAssertEqual(q.lifetimeBytes, 600 * 48000)
    }
}
