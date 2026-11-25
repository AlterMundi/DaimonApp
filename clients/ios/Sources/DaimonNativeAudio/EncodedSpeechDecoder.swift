import AudioToolbox
import AVFAudio
import Foundation

/// One worker consumes the verified MP3 source in order and emits bounded 24kHz
/// mono PCM16 buffers. It owns no player, audio session, URL or microphone.
/// Emitted PCM is decoded preparation, never a playback/hearing receipt.
final class EncodedSpeechDecoder {
    enum Refusal: Error { case invalid, unsupported, parser(OSStatus), conversion, capacity, closed }
    private var parser: AudioFileStreamID?
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?
    private let outputFormat: AVAudioFormat
    private let maximumPCMFrames: Int
    private let emit: (Data) throws -> Void
    private var failure: Error?
    private var started = false
    private var source: VerifiedEncodedAudioSource?
    private(set) var decodedFrames = 0

    init(maximumPCMFrames: Int = 24000 * 300, emit: @escaping (Data) throws -> Void) throws {
        guard (1...(24000 * 600)).contains(maximumPCMFrames),
              let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24000,
                                         channels: 1, interleaved: true) else { throw Refusal.invalid }
        self.maximumPCMFrames = maximumPCMFrames; self.emit = emit; outputFormat = output
        let status = AudioFileStreamOpen(Unmanaged.passUnretained(self).toOpaque(),
            { context, stream, property, _ in
                let owner = Unmanaged<EncodedSpeechDecoder>.fromOpaque(context).takeUnretainedValue()
                guard owner.failure == nil else { return }
                do { try owner.property(stream, property) } catch { owner.failure = error }
            }, { context, bytes, packets, data, descriptions in
                let owner = Unmanaged<EncodedSpeechDecoder>.fromOpaque(context).takeUnretainedValue()
                guard owner.failure == nil else { return }
                do { try owner.packets(bytes: bytes, count: packets, data: data, descriptions: descriptions) }
                catch { owner.failure = error }
            }, kAudioFileMP3Type, &parser)
        guard status == noErr, parser != nil else { throw Refusal.parser(status) }
    }
    /// Blocking reads belong to a dedicated decoder worker. This method is
    /// single-use; source retirement or errors cannot restart a decoder.
    func run(_ selected: VerifiedEncodedAudioSource, readSize: Int = 32768) throws {
        guard !started else { throw Refusal.closed }
        guard (1...32768).contains(readSize) else { throw Refusal.invalid }
        started = true; source = selected
        defer { selected.close(); source = nil; closeParser() }
        do {
            var offset = 0
            while let data = try selected.read(at: offset, length: readSize) {
                guard let parser else { throw Refusal.closed }
                let status = withExtendedLifetime(self) {
                    data.withUnsafeBytes { AudioFileStreamParseBytes(parser, UInt32(data.count), $0.baseAddress, []) }
                }
                if let failure { throw failure }
                guard status == noErr else { throw Refusal.parser(status) }
                offset += data.count
            }
            guard converter != nil else { throw Refusal.unsupported }
            try convert(nil, terminal: true)
            guard decodedFrames > 0 else { throw Refusal.invalid }
        } catch { failure = error; throw error }
    }
    private func property(_ stream: AudioFileStreamID, _ property: AudioFileStreamPropertyID) throws {
        guard property == kAudioFileStreamProperty_DataFormat else { return }
        var description = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        let status = AudioFileStreamGetProperty(stream, property, &size, &description)
        guard status == noErr else { throw Refusal.parser(status) }
        guard converter == nil, Int(size) == MemoryLayout<AudioStreamBasicDescription>.size,
              description.mFormatID == kAudioFormatMPEGLayer3,
              description.mSampleRate.isFinite, (8000...48000).contains(description.mSampleRate),
              (1...2).contains(description.mChannelsPerFrame),
              (1...4608).contains(description.mFramesPerPacket),
              let input = AVAudioFormat(streamDescription: &description),
              let selected = AVAudioConverter(from: input, to: outputFormat) else { throw Refusal.unsupported }
        inputFormat = input; converter = selected
    }
    private func packets(bytes: UInt32, count: UInt32, data: UnsafeRawPointer,
                         descriptions: UnsafeMutablePointer<AudioStreamPacketDescription>?) throws {
        guard let inputFormat, converter != nil, (1...65536).contains(bytes),
              (1...2048).contains(count) else { throw Refusal.invalid }
        let packetSize = Int(inputFormat.streamDescription.pointee.mBytesPerPacket)
        var ranges: [(Int, Int, UInt32)] = [], lastEnd = 0
        // Validate the complete callback before consuming any of its packets.
        for n in 0..<Int(count) {
            let start: Int, length: Int, frames: UInt32
            if let descriptions {
                let row = descriptions[n]
                guard let position = Int(exactly: row.mStartOffset) else { throw Refusal.invalid }
                start = position; length = Int(row.mDataByteSize); frames = row.mVariableFramesInPacket
            } else {
                guard packetSize > 0, packetSize <= 32768 else { throw Refusal.invalid }
                start = n * packetSize; length = packetSize; frames = 0
            }
            guard start >= lastEnd, start <= Int(bytes), (1...32768).contains(length),
                  length <= Int(bytes) - start, frames <= 4608 else { throw Refusal.invalid }
            ranges.append((start, length, frames)); lastEnd = start + length
        }
        for (start, length, frames) in ranges {
            let buffer = AVAudioCompressedBuffer(format: inputFormat, packetCapacity: 1, maximumPacketSize: length)
            guard Int(buffer.byteCapacity) >= length else { throw Refusal.capacity }
            buffer.data.copyMemory(from: data.advanced(by: start), byteCount: length)
            buffer.byteLength = UInt32(length); buffer.packetCount = 1
            if let target = buffer.packetDescriptions {
                target.pointee = AudioStreamPacketDescription(mStartOffset: 0,
                    mVariableFramesInPacket: frames, mDataByteSize: UInt32(length))
            } else if packetSize == 0 { throw Refusal.invalid }
            try convert(buffer, terminal: false)
        }
    }
    private func convert(_ input: AVAudioCompressedBuffer?, terminal: Bool) throws {
        guard let converter else { throw Refusal.unsupported }
        var supplied = false
        // Each MP3 packet has at most4608 source frames at8kHz. This bounds
        // conversion/drain work even if a codec returns an unexpected status.
        for _ in 0..<16 {
            guard source?.isClosed == false,
                  let output = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: 4096) else { throw Refusal.closed }
            var error: NSError?
            let status = converter.convert(to: output, error: &error) { _, state in
                if let input, !supplied { supplied = true; state.pointee = .haveData; return input }
                state.pointee = terminal ? .endOfStream : .noDataNow; return nil
            }
            guard error == nil, status != .error else { throw Refusal.conversion }
            if output.frameLength > 0 {
                let frames = Int(output.frameLength)
                guard frames <= maximumPCMFrames - decodedFrames,
                      let channel = output.int16ChannelData?[0], source?.isClosed == false else { throw Refusal.capacity }
                let data = Data(bytes: channel, count: frames * 2)
                try emit(data); decodedFrames += frames
            }
            switch status {
            case .haveData: continue
            case .inputRanDry:
                guard !terminal, input == nil || supplied else { throw Refusal.conversion }
                return
            case .endOfStream:
                guard terminal else { throw Refusal.conversion }; return
            case .error: throw Refusal.conversion
            @unknown default: throw Refusal.conversion
            }
        }
        throw Refusal.capacity
    }
    private func closeParser() {
        if let parser { AudioFileStreamClose(parser); self.parser = nil }
        converter = nil; inputFormat = nil
    }
    deinit { closeParser() }
}
