import Foundation
import XCTest
@testable import DaimonNativeAudio

@MainActor private final class SessionFixture: AudioSessionDevice {
    var starts = 0, stops = 0, failStart = false, failStop = false
    func activate() throws { starts += 1; if failStart { throw AudioSessionOwnership.Refusal.unavailable } }
    func deactivate() throws { stops += 1; if failStop { throw AudioSessionOwnership.Refusal.unavailable } }
}

final class AudioSessionOwnershipTests: XCTestCase {
    @MainActor func testIndependentHoldersAndStaleReleaseCannotAbandonFreshOwner() async throws {
        let device = SessionFixture(), session = AudioSessionOwnership(device: device)
        let speech = UUID(), beacon = UUID(), next = UUID()
        try session.acquire(speech, cancelled: {}); try session.acquire(beacon, cancelled: {})
        XCTAssertThrowsError(try session.acquire(UUID(), cancelled: {}))
        XCTAssertEqual(device.starts, 1)
        session.release(speech); XCTAssertEqual(device.stops, 0)
        session.release(beacon); XCTAssertEqual(device.stops, 1)
        try session.acquire(next, cancelled: {}); session.release(speech)
        XCTAssertEqual(device.stops, 1); XCTAssertEqual(session.count, 1)
        session.release(next); XCTAssertEqual(device.stops, 2)
    }
    @MainActor func testCancellationClosesOnlyOwnedSnapshotAndDoesNotResume() async throws {
        let device = SessionFixture(), session = AudioSessionOwnership(device: device), owner = UUID()
        var cancelled = 0
        try session.acquire(owner) {
            cancelled += 1
            XCTAssertThrowsError(try session.acquire(UUID(), cancelled: {}))
            session.release(owner)
        }
        session.cancelOwned(); session.cancelOwned()
        XCTAssertEqual(cancelled, 1); XCTAssertEqual(device.starts, 1)
        XCTAssertEqual(device.stops, 1); XCTAssertEqual(session.count, 0)
    }
    @MainActor func testUnknownDeactivationBlocksNewOwnersUntilExplicitExactRecovery() async throws {
        let device = SessionFixture(), session = AudioSessionOwnership(device: device), owner = UUID()
        try session.acquire(owner, cancelled: {}); device.failStop = true
        XCTAssertFalse(session.release(owner)); XCTAssertEqual(session.unconfirmedRelease, owner)
        session.release(owner); session.cancelOwned()
        XCTAssertEqual(device.stops, 1)
        XCTAssertThrowsError(try session.acquire(UUID(), cancelled: {})); XCTAssertEqual(device.starts, 1)
        device.failStop = false
        XCTAssertFalse(session.recoverRelease(UUID())); XCTAssertEqual(device.stops, 1)
        XCTAssertTrue(session.recoverRelease(owner)); XCTAssertNil(session.unconfirmedRelease)
        try session.acquire(UUID(), cancelled: {})
    }
    @MainActor func testPartialActivationFailureRetainsFailedCleanupWithoutRetry() async throws {
        let device = SessionFixture(), session = AudioSessionOwnership(device: device), owner = UUID()
        device.failStart = true; device.failStop = true
        XCTAssertThrowsError(try session.acquire(owner, cancelled: {}))
        XCTAssertEqual(session.unconfirmedRelease, owner); XCTAssertEqual(session.count, 0)
        XCTAssertThrowsError(try session.acquire(owner, cancelled: {}))
        XCTAssertEqual(device.starts, 1); XCTAssertEqual(device.stops, 1)
    }
}
