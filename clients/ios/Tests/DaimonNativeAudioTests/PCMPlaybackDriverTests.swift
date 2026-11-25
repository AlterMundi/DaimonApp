import AVFAudio
import Foundation
import XCTest
@testable import DaimonNativeAudio

@MainActor private final class OutputFixture: PCMOutputDevice {
    var completions: [@Sendable () -> Void] = []
    var starts = 0, pauses = 0, stops = 0
    var fail = false
    func prepare() throws {}
    func schedule(_ data: Data, completion: @escaping @Sendable () -> Void) throws {
        if fail { throw PCMPlaybackQueue.Refusal.invalidSpan }
        completions.append(completion)
    }
    func start() throws { starts += 1 }
    func pause() { pauses += 1 }
    func stop() { stops += 1 }
}

final class PCMPlaybackDriverTests: XCTestCase {
    @MainActor private func settle() async { await withCheckedContinuation { next in DispatchQueue.main.async { next.resume() } } }
    @MainActor private func append(_ driver: PCMPlaybackDriver, _ n: Int, _ id: String) throws {
        let data = Data(repeating: 0, count: 4)
        try driver.append(sequence: n, utterance: id, end: (n + 1) * 4,
                          data: data, sha256: PCMPlaybackQueue.digest(data))
    }
    @MainActor func testOutOfOrderDeviceCallbacksOnlyAdvanceContiguousPlayback() async throws {
        let output = OutputFixture(), id = UUID().uuidString.lowercased()
        var positions: [Int] = [], releases = 0
        let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: {},
            deactivate: { releases += 1 }, clock: { 0 }) { event in
                if case .progress(let changed) = event, let n = changed[id] { positions.append(n) }
            }
        defer { driver.close() }
        try append(driver, 0, id); try append(driver, 1, id)
        XCTAssertEqual(positions, [])
        output.completions[1](); await settle(); XCTAssertEqual(positions, [])
        output.completions[0](); await settle(); XCTAssertEqual(positions, [8])
        XCTAssertEqual(releases, 1)
        output.completions[0](); await settle(); XCTAssertEqual(positions, [8])
    }
    @MainActor func testFlushAndCloseFenceLateCallbacksWithoutReplenishingSequence() async throws {
        let output = OutputFixture(), id = UUID().uuidString.lowercased()
        var receipts = 0
        let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: {},
            deactivate: {}, clock: { 0 }) { if case .progress = $0 { receipts += 1 } }
        try append(driver, 0, id); let old = output.completions[0]
        try driver.flush(); old(); await settle(); XCTAssertEqual(receipts, 0)
        XCTAssertThrowsError(try append(driver, 0, id))
        let next = UUID().uuidString.lowercased(), data = Data(repeating: 0, count: 4)
        try driver.append(sequence: 1, utterance: next, end: 4, data: data, sha256: PCMPlaybackQueue.digest(data))
        driver.close(); output.completions[1](); await settle(); XCTAssertEqual(receipts, 0)
        XCTAssertThrowsError(try append(driver, 2, next))
    }
    @MainActor func testPauseBoundsScheduledBuffersAndRequiresExplicitResume() async throws {
        let output = OutputFixture(), id = UUID().uuidString.lowercased()
        var acquisitions = 0
        let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: { acquisitions += 1 },
            deactivate: {}, clock: { 0 }, emit: { _ in })
        defer { driver.close() }
        for n in 0..<10 { try append(driver, n, id) }
        XCTAssertEqual(output.completions.count, 8); try driver.pause()
        output.completions[0](); await settle(); XCTAssertEqual(output.completions.count, 8)
        try driver.resume(); XCTAssertEqual(output.completions.count, 9); XCTAssertEqual(acquisitions, 2)
    }
    @MainActor func testDeadlineAndDeviceFailureCloseWithoutRetry() async throws {
        let output = OutputFixture(), id = UUID().uuidString.lowercased()
        var now: TimeInterval = 0, closed = 0
        let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: {},
            deactivate: {}, clock: { now }) { if case .closed = $0 { closed += 1 } }
        now = 300; XCTAssertThrowsError(try append(driver, 0, id)); XCTAssertEqual(closed, 1)
        driver.close(); XCTAssertEqual(closed, 1)
        let failed = OutputFixture(); failed.fail = true
        let other = try PCMPlaybackDriver(seconds: 300, device: failed, activate: {}, deactivate: {}, clock: { 0 }, emit: { _ in })
        XCTAssertThrowsError(try append(other, 0, id)); failed.fail = false
        XCTAssertThrowsError(try append(other, 0, id)); XCTAssertEqual(failed.completions.count, 0)
    }
    @MainActor func testActualApplePCMBufferPreservesSignedLittleEndianSamples() async throws {
        let buffer = try ApplePCMOutput.buffer(Data([0, 128, 0, 0, 255, 127]))
        XCTAssertEqual(buffer.format.sampleRate, 24000); XCTAssertEqual(buffer.frameLength, 3)
        let channel = try XCTUnwrap(buffer.floatChannelData?[0])
        XCTAssertEqual(channel[0], -1); XCTAssertEqual(channel[1], 0)
        XCTAssertEqual(channel[2], Float(32767) / 32768)
        XCTAssertThrowsError(try ApplePCMOutput.buffer(Data([0])))
    }
    @MainActor func testDecoderWaitsForPlayedCapacityInsteadOfExpandingTheByteQueue() async throws {
        let output = OutputFixture(), id = UUID().uuidString.lowercased()
        let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: {},
            deactivate: {}, clock: { 0 }, emit: { _ in })
        defer { driver.close() }
        let data = Data(repeating: 0, count: 32000)
        for n in 0..<45 {
            try driver.append(sequence: n, utterance: id, end: (n + 1) * data.count,
                              data: data, sha256: PCMPlaybackQueue.digest(data))
        }
        var entered = false, admitted = false
        let waiter = Task { entered = true; try await driver.waitForCapacity(8192); admitted = true }
        await settle(); XCTAssertTrue(entered); XCTAssertFalse(admitted)
        XCTAssertEqual(output.completions.count, 8)
        output.completions[0](); await settle()
        try await waiter.value; XCTAssertTrue(admitted)
        XCTAssertEqual(output.completions.count, 9, "Only playback completion frees scheduled capacity")
    }
    @MainActor func testSpanBackpressureAlsoRetiresOnFlushStopAndTaskCancellation() async throws {
        for operation in 0..<3 {
            let output = OutputFixture(), id = UUID().uuidString.lowercased()
            let driver = try PCMPlaybackDriver(seconds: 300, device: output, activate: {},
                deactivate: {}, clock: { 0 }, emit: { _ in })
            defer { driver.close() }
            for n in 0..<512 { try append(driver, n, id) }
            var entered = false, admitted = false
            let waiter = Task { entered = true; try await driver.waitForCapacity(2); admitted = true }
            await settle(); XCTAssertTrue(entered); XCTAssertFalse(admitted)
            if operation == 0 { try driver.flush() }
            else if operation == 1 { driver.close() }
            else { waiter.cancel() }
            switch await waiter.result {
            case .success: XCTFail("Retired decoder wait admitted stale PCM")
            case .failure: break
            }
            output.completions[0](); await settle()
            XCTAssertFalse(admitted)
            if operation != 1 {
                if operation == 2 { try driver.flush() }
                try await driver.waitForCapacity(2)
                let data = Data([0,0]), fresh = UUID().uuidString.lowercased()
                try driver.append(sequence: 512, utterance: fresh, end: 2,
                                  data: data, sha256: PCMPlaybackQueue.digest(data))
            }
        }
    }
}
