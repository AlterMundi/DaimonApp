import Foundation
import XCTest
@testable import DaimonNativeAudio

final class InteractionBridgeTests: XCTestCase {
    private let document = UUID().uuidString.lowercased()
    private func message(_ fields: [String: Any]) throws -> PCMBridgeMessage {
        var fields = fields; fields["document_id"] = document
        return try PCMBridgeMessage(String(data: JSONSerialization.data(withJSONObject: fields), encoding: .utf8)!)
    }
    func testHomeSelectionAndNativePagesDoNotWidenToLoginOrOtherOrigins() throws {
        let home = try InteractionHome(" https://Example.org:443/interaction/ ")
        XCTAssertEqual(home.origin.absoluteString, "https://example.org")
        XCTAssertEqual(home.conversation.absoluteString, "https://example.org/interaction/?view=conversation&client=standalone")
        XCTAssertTrue(home.allowsPage(home.conversation), "URL path=\(home.conversation.path), components path=\(URLComponents(url:home.conversation,resolvingAgainstBaseURL:true)?.path ?? "missing")")
        for value in ["http://example.org", "https://user:secret@example.org", "https://example.org:8443",
                      "https://example.org/?token=secret", "https://example.org/#other", "https://example.org/works/"] {
            XCTAssertThrowsError(try InteractionHome(value))
        }
        for value in ["https://other.example/interaction/", "https://auth.dmn.homes/interaction/",
                      "https://example.org/interaction-evil/", "https://example.org:8443/interaction/",
                      "https://example.org/interaction/../works/", "https://example.org/interaction/%2e%2e/works/",
                      "https://user@example.org/interaction/"] {
            XCTAssertFalse(home.allowsPage(try XCTUnwrap(URL(string: value))), value)
        }
    }
    func testOnlyTheClosedPCMContractAndCanonicalDocumentCanEnter() throws {
        XCTAssertEqual(try message(["command":"hello"]).document, document)
        XCTAssertEqual(try message(["command":"pcm_begin","id":"pcm_1","seconds":600]).integer("seconds",300...600),600)
        let invalid: [[String: Any]] = [
            ["command":"beacon_begin","id":"pcm_1"], ["command":"begin","id":"pcm_1"],
            ["command":"pcm_begin","id":"pcm_1","seconds":300,"url":"https://example.org"],
            ["command":"stop","id":"pcm_0"], ["command":"stop","id":"foreign"],
            ["command":"session","enabled":1], ["command":"stop"]
        ]
        for fields in invalid { XCTAssertThrowsError(try message(fields)) }
        XCTAssertThrowsError(try PCMBridgeMessage("{\"command\":\"hello\",\"document_id\":\"invalid\"}"))
        XCTAssertThrowsError(try PCMBridgeMessage(String(repeating:" ",count:45001)))
    }
    func testBooleanFractionAndOversizedDurationCannotBecomeNativeIntegers() throws {
        let invalid: [Any] = [true, 300.5, -1, 601, "600", NSNull()]
        for seconds in invalid {
            let value = try message(["command":"pcm_begin","id":"pcm_1","seconds":seconds])
            XCTAssertThrowsError(try value.integer("seconds",300...600))
        }
        XCTAssertEqual(try message(["command":"session","enabled":false]).command,"session")
    }
    func testCaptureOwnershipCommandsAreClosedAndDoNotGrantMediaOrAcceptOtherDocuments() throws {
        let owner = UUID().uuidString.lowercased()
        func raw(_ value: [String:Any]) throws -> String {
            String(data:try JSONSerialization.data(withJSONObject:value),encoding:.utf8)!
        }
        let fields: [String:Any] = ["command":"capture_begin","document_id":document,"owner":owner]
        XCTAssertEqual(try CaptureBridgeMessage(raw(fields)).owner.uuidString.lowercased(),owner)
        var end = fields; end["command"] = "capture_end"
        XCTAssertEqual(try CaptureBridgeMessage(raw(end)).command,"capture_end")
        for (key,value) in [("command","grant"),("owner","other"),("document_id","invalid")] {
            var changed = fields; changed[key] = value
            XCTAssertThrowsError(try CaptureBridgeMessage(raw(changed)))
        }
        var extra = fields; extra["seconds"] = 601
        XCTAssertThrowsError(try CaptureBridgeMessage(raw(extra)))
        XCTAssertThrowsError(try CaptureBridgeMessage(String(repeating:" ",count:513)))
    }
    func testCaptureConnectionsUseClosedCanonicalFlatOwnerLinks() throws {
        let owner = UUID().uuidString.lowercased(), visit = UUID().uuidString.lowercased()
        var fields: [String:Any] = ["command":"capture_connection","document_id":document,"owner":owner,"visit":visit]
        func parse(_ value: [String:Any]) throws -> CaptureBridgeMessage {
            try CaptureBridgeMessage(String(data:JSONSerialization.data(withJSONObject:value),encoding:.utf8)!)
        }
        XCTAssertEqual(try parse(fields).visit?.uuidString.lowercased(),visit)
        XCTAssertNil(try parse(fields).predecessor)
        fields["predecessor"] = UUID().uuidString.lowercased()
        XCTAssertNotNil(try parse(fields).predecessor)
        for (key,value) in [("visit","other"),("predecessor",""),("document_id","OTHER")] {
            var changed = fields; changed[key] = value
            XCTAssertThrowsError(try parse(changed))
        }
        var extra = fields; extra["seconds"] = 601
        XCTAssertThrowsError(try parse(extra))
        var wrong = fields; wrong["command"] = "capture_begin"
        XCTAssertThrowsError(try parse(wrong))
        var nested = fields; nested["visit"] = ["id":visit]
        XCTAssertThrowsError(try parse(nested))
    }
    func testOnlyCurrentDistinctPhysicalSuccessorsAdvanceCaptureLease() throws {
        var lease = CaptureConnectionLease()
        let first = UUID(), next = UUID(), last = UUID()
        XCTAssertFalse(try lease.connect(first,from:nil))
        XCTAssertEqual(lease.generation,0)
        XCTAssertFalse(try lease.connect(first,from:nil),"Duplicate initial binding cannot extend capture")
        XCTAssertThrowsError(try lease.connect(next,from:UUID()))
        XCTAssertEqual(lease.visit,first)
        XCTAssertTrue(try lease.connect(next,from:first)); XCTAssertEqual(lease.generation,1)
        XCTAssertFalse(try lease.connect(next,from:first),"Lost acknowledgments never rearm the deadline")
        XCTAssertEqual(lease.generation,1)
        XCTAssertThrowsError(try lease.connect(first,from:next),"A retired physical connection cannot become current again")
        XCTAssertThrowsError(try lease.connect(last,from:first),"A stale predecessor cannot advance capture")
        XCTAssertTrue(try lease.connect(last,from:next)); XCTAssertEqual(lease.generation,2)
    }
    func testPhysicalConnectionHistoryIsBoundedWithoutExtendingDuplicateDeadline() throws {
        var lease = CaptureConnectionLease(), previous: UUID?
        for _ in 0..<512 {
            let next = UUID(); _ = try lease.connect(next,from:previous); previous = next
        }
        XCTAssertEqual(lease.generation,511)
        XCTAssertThrowsError(try lease.connect(UUID(),from:previous))
        XCTAssertEqual(lease.generation,511)
    }
    private let beaconID = "beacon_aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    private func beaconFields() -> [String:Any] {
        ["command":"beacon_frame","id":beaconID,"frequencies":[40.4,80.8,121.2,161.6,282.8,444.4],
         "pulses":Array(repeating:0,count:6),"weights":[1,0,0,0,0,0],"depth":0.2,"level":0.3,
         "transition_ms":180,"expires_at_ms":123456001]
    }
    func testBeaconOwnersHaveCanonicalIndependentClosedCommands() throws {
        XCTAssertEqual(try message(["command":"beacon_begin","id":beaconID]).id,beaconID)
        XCTAssertEqual(try message(["command":"beacon_stop","id":beaconID]).command,"beacon_stop")
        let wrong: [[String:Any]] = [
            ["command":"beacon_begin","id":"pcm_1"],
            ["command":"pcm_begin","id":beaconID,"seconds":600],
            ["command":"beacon_begin","id":beaconID.uppercased()],
            ["command":"beacon_begin","id":beaconID,"enabled":true],
            ["command":"beacon_level","id":beaconID,"level":0.2],
            ["command":"beacon_stop","id":beaconID,"expires_at_ms":1000]
        ]
        for fields in wrong { XCTAssertThrowsError(try message(fields)) }
        let raw = "{\"command\":\"beacon_begin\",\"id\":\"\(beaconID)\",\"document_id\":\"\(document)\"}"
        XCTAssertThrowsError(try PCMBridgeMessage(raw+String(repeating:" ",count:4096)))
    }
    @MainActor func testBeaconFramePreservesAbsoluteMonotonicExpiryAndNumericBounds() async throws {
        let value = try message(beaconFields()), frame = try value.beaconFrame()
        XCTAssertEqual(frame.expires,123456.001,accuracy:0.000001)
        XCTAssertEqual(frame.weights,[1,0,0,0,0,0]); XCTAssertEqual(frame.transition,180)
        for key in ["depth","level","transition_ms","expires_at_ms"] {
            var fields = beaconFields(); fields[key] = true
            XCTAssertThrowsError(try message(fields).beaconFrame(),key)
        }
        let invalidExpiries: [Any] = [-1,1.5,9007199254740992.0,"1000",NSNull()]
        for expiry in invalidExpiries {
            var fields = beaconFields(); fields["expires_at_ms"] = expiry
            XCTAssertThrowsError(try message(fields).beaconFrame())
        }
        for key in ["frequencies","pulses","weights"] {
            var fields = beaconFields(); fields[key] = [true,0,0,0,0,0]
            XCTAssertThrowsError(try message(fields).beaconFrame(),key)
            fields[key] = [1,0,0,0,0]
            XCTAssertThrowsError(try message(fields).beaconFrame(),key)
        }
        var fields = beaconFields(); fields["weights"] = [1,1,0,0,0,0]
        XCTAssertThrowsError(try message(fields).beaconFrame())
        fields = beaconFields(); fields["frequencies"] = [10800,80.8,121.2,161.6,282.8,444.4]
        XCTAssertThrowsError(try message(fields).beaconFrame())
    }
    func testBeaconGainCannotCarryOrCoerceAnObservationDeadline() throws {
        let valid = try message(["command":"beacon_level","id":beaconID,"level":0.2,"transition_ms":80])
        XCTAssertEqual(try valid.number("level",0...0.8),0.2)
        XCTAssertEqual(try valid.integer("transition_ms",20...2000),80)
        XCTAssertThrowsError(try valid.beaconFrame())
        XCTAssertThrowsError(try message(["command":"beacon_level","id":beaconID,"level":0.2,"transition_ms":80,"expires_at_ms":1000]))
        let invalidLevels: [Any] = [true,-0.1,0.81,"0.2",NSNull()]
        for level in invalidLevels {
            let value = try message(["command":"beacon_level","id":beaconID,"level":level,"transition_ms":80])
            XCTAssertThrowsError(try value.number("level",0...0.8))
        }
    }

}
