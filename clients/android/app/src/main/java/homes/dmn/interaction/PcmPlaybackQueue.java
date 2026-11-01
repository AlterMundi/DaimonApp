package homes.dmn.interaction;

import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

/** Bounded verified PCM spans. Submitted bytes are never playback receipts. */
final class PcmPlaybackQueue {
    static final int MAX_QUEUED = 30 * 48000, MAX_SESSION = 300 * 48000;
    static final class Chunk {
        ByteBuffer buffer;
        final String utterance;
        final int begin, end, sourceBegin;
        int written;
        Chunk(String utterance, int begin, int sourceBegin, byte[] data) {
            this.utterance = utterance; this.begin = begin; this.end = begin + data.length; this.sourceBegin = sourceBegin;
            buffer = ByteBuffer.allocateDirect(data.length); buffer.put(data).flip();
        }
    }
    private final Deque<Chunk> writes = new ArrayDeque<>(), spans = new ArrayDeque<>();
    private final Map<String,Integer> received = new LinkedHashMap<>(), reported = new LinkedHashMap<>();
    private final Set<String> retired = new HashSet<>();
    private int sequence, lifetime, appended, submitted, played;

    void append(int next, String utterance, int end, byte[] data, String hash) throws Exception {
        if (utterance == null || !UUID.fromString(utterance).toString().equals(utterance)
            || next != sequence || data.length < 2 || data.length > 32768 || data.length % 2 != 0
            || !VerifiedAudioBuffer.hash(data).equals(hash) || retired.contains(utterance)
            || (!received.containsKey(utterance) && received.size() >= 128)
            || spans.size() >= 512 || lifetime + data.length > MAX_SESSION
            || appended - played + data.length > MAX_QUEUED) throw new IllegalArgumentException("Invalid bounded PCM span");
        int previous = received.getOrDefault(utterance, 0);
        if (end != previous + data.length) throw new IllegalArgumentException("PCM source continuity changed");
        Chunk chunk = new Chunk(utterance, appended, previous, data);
        writes.add(chunk); spans.add(chunk); received.put(utterance, end);
        appended += data.length; lifetime += data.length; sequence++;
    }
    Chunk next() { return writes.peek(); }
    void wrote(int count) {
        Chunk chunk = writes.peek();
        if (chunk == null || count < 0 || count % 2 != 0 || count > chunk.end - chunk.begin - chunk.written)
            throw new IllegalArgumentException("Invalid PCM write position");
        chunk.written += count; submitted += count;
        chunk.buffer.position(chunk.written);
        if (chunk.written == chunk.end - chunk.begin) { writes.remove(); chunk.buffer = null; }
    }
    Map<String,Integer> advance(int position) {
        if (position < played || position > submitted || position % 2 != 0)
            throw new IllegalArgumentException("Invalid PCM playback position");
        played = position; Map<String,Integer> changed = new LinkedHashMap<>();
        for (Chunk span : spans) {
            if (played <= span.begin) break;
            int count = span.sourceBegin + Math.min(played, span.end) - span.begin;
            if (count > reported.getOrDefault(span.utterance, 0)) { reported.put(span.utterance, count); changed.put(span.utterance, count); }
        }
        while (!spans.isEmpty() && spans.peek().end <= played) spans.remove();
        return changed;
    }
    void flush() {
        retired.addAll(received.keySet()); writes.clear(); spans.clear(); appended = submitted = played = 0;
        // Sequence, lifetime and source identities remain fenced across flush.
    }
    int submitted() { return submitted; }
    int queued() { return appended - played; }
    int played() { return played; }
}
