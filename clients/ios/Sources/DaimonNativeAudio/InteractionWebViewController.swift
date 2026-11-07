#if os(iOS)
import Foundation
import UIKit
import WebKit

/// Existing hosted Conversation and shared SSO, with a main-frame-only PCM bridge.
/// adapterSource must be the app-bundled native-audio.js, never downloaded input.
@MainActor public final class InteractionWebViewController: UIViewController, WKNavigationDelegate, WKScriptMessageHandler {
    private let home: InteractionHome
    private let session: IOSSpokenAudioSession
    private let adapterSource: String
    private var web: WKWebView!
    private var document: String?
    private var retired: Set<String> = []
    private var output: PCMPlaybackDriver?
    private var outputID: String?
    private var backgroundObserver: NSObjectProtocol?

    public init(home: InteractionHome, session: IOSSpokenAudioSession, adapterSource: String) throws {
        guard adapterSource.utf8.count <= 131072 else { throw PCMBridgeMessage.Refusal.invalid }
        self.home = home; self.session = session; self.adapterSource = adapterSource
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("Use the selected home initializer") }
    private static func literal(_ value: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [value])
        return String(data: data, encoding: .utf8)!.dropFirst().dropLast().description
    }
    public override func loadView() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        configuration.userContentController.add(WeakMessageHandler(self), name: "audio")
        let script = """
        (()=>{if(location.origin!==\(Self.literal(home.origin.absoluteString))||!location.pathname.startsWith('/interaction/'))return;
        const documentID=crypto.randomUUID();window.__DaimonAudioDocument=documentID;
        window.DaimonAudio={postMessage:raw=>{const value=JSON.parse(raw);value.document_id=documentID;window.webkit.messageHandlers.audio.postMessage(JSON.stringify(value));}};
        \(adapterSource)
        // Keep native capabilities unadvertised until the actual iOS journey qualifies.
        Object.assign(window.NativeSpeechAudio,{mount:()=>undefined,pcm:false,webrtcPcm:false,progressive:false,backgroundPlayback:false,beacon:false});
        })();
        """
        configuration.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: configuration); web.navigationDelegate = self; view = web
        backgroundObserver = NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification,
            object: nil, queue: nil) { [weak self] _ in Task { @MainActor in self?.suspendPage() } }
        web.load(URLRequest(url: home.conversation))
    }
    private func closeOutput() {
        let old = output; output = nil; outputID = nil; old?.close()
    }
    private func suspendPage() {
        if let document {
            web.evaluateJavaScript("if(window.__DaimonAudioDocument===\(Self.literal(document))){window.NativeSpeechAudio?.background();}")
        }
        closeOutput(); session.leaveForeground()
    }
    public func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if let document { retired.insert(document) }
        document = nil; closeOutput()
    }
    public func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if let document { retired.insert(document) }
        document = nil; closeOutput() // No automatic page/input or media replay.
    }
    public func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, url.scheme == "https", url.user == nil, url.password == nil,
              url.port == nil || url.port == 443 else { decisionHandler(.cancel); return }
        if url.host == home.origin.host || url.host == "auth.dmn.homes" { decisionHandler(.allow) }
        else {
            decisionHandler(.cancel)
            if action.navigationType == .linkActivated { UIApplication.shared.open(url) }
        }
    }
    public func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        let frame = message.frameInfo, origin = frame.securityOrigin
        guard message.webView === web, frame.isMainFrame, origin.protocol == "https",
              origin.host.lowercased() == home.origin.host?.lowercased(), [0,443].contains(origin.port),
              let url = frame.request.url, home.allowsPage(url), let current = web.url, home.allowsPage(current),
              let raw = message.body as? String, let value = try? PCMBridgeMessage(raw) else { return }
        if value.command == "hello" {
            guard document == nil, retired.count < 16, !retired.contains(value.document) else { return }
            document = value.document; return
        }
        guard value.document == document else { return }
        if value.command == "session" { return } // No background-listening grant.
        guard let id = value.id else { return }
        if value.command == "stop" { if outputID == id { closeOutput() }; return }
        guard UIApplication.shared.applicationState == .active else { return }
        do {
            if value.command == "pcm_begin" {
                guard output == nil else { throw PCMBridgeMessage.Refusal.invalid }
                let seconds = try value.integer("seconds", 300...600), page = value.document
                outputID = id
                output = try session.makeOutput(seconds: seconds) { [weak self] event in
                    guard let self, self.document == page, self.outputID == id else { return }
                    switch event {
                    case .ready: self.send(["type":"pcm_ready", "session_seconds":seconds], id: id, page: page)
                    case .progress(let positions): self.send(["type":"pcm_progress", "positions":positions.map { ["utterance":$0.key,"played_bytes":$0.value] }], id:id,page:page)
                    case .playing: self.send(["type":"playing"], id:id,page:page)
                    case .paused: self.send(["type":"pause"], id:id,page:page)
                    case .quiet: self.send(["type":"ended"], id:id,page:page)
                    case .closed: self.output = nil; self.outputID = nil; self.send(["type":"focuslost"],id:id,page:page)
                    case .unavailable: self.send(["type":"error"],id:id,page:page)
                    }
                }
                return
            }
            guard outputID == id, let output else { return }
            switch value.command {
            case "pcm_chunk":
                guard let text = value.fields["data"] as? String, text.utf8.count <= 43692,
                      let data = Data(base64Encoded: text), let utterance = value.fields["utterance"] as? String,
                      let hash = value.fields["sha256"] as? String else { throw PCMBridgeMessage.Refusal.invalid }
                try output.append(sequence: value.integer("sequence",0...14400000), utterance:utterance,
                                  end:value.integer("end",2...28800000),data:data,sha256:hash)
            case "pcm_flush": try output.flush()
            case "pause": try output.pause()
            case "play": try output.resume()
            default: throw PCMBridgeMessage.Refusal.invalid
            }
        } catch { if outputID == id { closeOutput() }; send(["type":"error"],id:id,page:value.document) }
    }
    private func send(_ fields: [String: Any], id: String, page: String) {
        var value = fields; value["id"] = id
        guard let data = try? JSONSerialization.data(withJSONObject:value), data.count <= 16384,
              let text = String(data:data,encoding:.utf8) else { return }
        web.evaluateJavaScript("if(window.__DaimonAudioDocument===\(Self.literal(page))){window.DaimonAudio?.onmessage?.({data:\(Self.literal(text))});}")
    }
    public override func viewDidDisappear(_ animated: Bool) { super.viewDidDisappear(animated); suspendPage() }
    public override func viewDidAppear(_ animated: Bool) { super.viewDidAppear(animated); session.enterForeground() }
    deinit { if let backgroundObserver { NotificationCenter.default.removeObserver(backgroundObserver) } }
}

@MainActor private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var owner: InteractionWebViewController?
    init(_ owner: InteractionWebViewController) { self.owner = owner }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        owner?.userContentController(userContentController,didReceive:message)
    }
}
#endif
