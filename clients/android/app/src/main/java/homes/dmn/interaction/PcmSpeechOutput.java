package homes.dmn.interaction;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Handler;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Map;
import java.util.Collections;
import java.util.function.Consumer;

/** PCM branch of the existing speech owner; nonblocking writes, no capture/network. */
final class PcmSpeechOutput {
    private final Handler handler;
    private final Runnable acquire, abandon;
    private final Consumer<JSONObject> emit;
    private final AudioTrack track;
    private final PcmPlaybackQueue queue = new PcmPlaybackQueue();
    private boolean closed, paused, playing;
    private long progressed = SystemClock.uptimeMillis();
    private final Runnable pump = this::pump;
    private final Runnable expiry = this::fail;

    PcmSpeechOutput(AudioAttributes attributes, Handler handler, Runnable acquire, Runnable abandon, Consumer<JSONObject> emit) {
        this.handler = handler; this.acquire = acquire; this.abandon = abandon; this.emit = emit;
        int minimum = AudioTrack.getMinBufferSize(24000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum < 1 || minimum > PcmPlaybackQueue.MAX_QUEUED) throw new IllegalStateException("PCM output unavailable");
        track = new AudioTrack.Builder().setAudioAttributes(attributes)
            .setAudioFormat(new AudioFormat.Builder().setSampleRate(24000).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(minimum, 4800))
            .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY).build();
        if (track.getState() != AudioTrack.STATE_INITIALIZED) { track.release(); throw new IllegalStateException("PCM output unavailable"); }
        handler.postDelayed(expiry, 300000);
    }
    private void event(String type, Map<String,Integer> positions) {
        if (closed) return;
        JSONObject value = new JSONObject(); JSONArray items = new JSONArray();
        try {
            for (Map.Entry<String,Integer> entry : positions.entrySet())
                items.put(new JSONObject().put("utterance", entry.getKey()).put("played_bytes", entry.getValue()));
            value.put("type", type).put("positions", items).put("queued_bytes", queue.queued());
        } catch (Exception error) { throw new IllegalStateException(error); }
        emit.accept(value);
    }
    private void observe() {
        // Playback head is unsigned frames; the five-minute bound is below wrap.
        int head = (int)Math.min(queue.submitted(), Integer.toUnsignedLong(track.getPlaybackHeadPosition()) * 2);
        Map<String,Integer> positions = queue.advance(head);
        if (!positions.isEmpty()) { progressed = SystemClock.uptimeMillis(); event("pcm_progress", positions); }
    }
    void append(int sequence, String utterance, int end, byte[] data, String hash) throws Exception {
        if (closed) throw new IllegalStateException("PCM output closed");
        queue.append(sequence, utterance, end, data, hash); handler.removeCallbacks(pump); pump();
    }
    private void pump() {
        if (closed || paused) return;
        try {
            observe();
            for (int n = 0; n < 4 && queue.next() != null; n++) {
                PcmPlaybackQueue.Chunk chunk = queue.next();
                int count = track.write(chunk.buffer, chunk.buffer.remaining(), AudioTrack.WRITE_NON_BLOCKING);
                if (count < 0) throw new IllegalStateException("PCM device write failed");
                queue.wrote(count); if (count == 0) break;
            }
            if (queue.queued() > 0) {
                if (!playing) { acquire.run(); track.play(); playing = true; progressed = SystemClock.uptimeMillis(); event("playing", Collections.emptyMap()); }
                if (SystemClock.uptimeMillis() - progressed > 30000) throw new IllegalStateException("PCM playback stalled");
                handler.postDelayed(pump, 20);
            } else if (playing) { track.pause(); playing = false; abandon.run(); event("ended", Collections.emptyMap()); }
        } catch (Exception error) { fail(); }
    }
    void pause() {
        if (closed || paused) return;
        observe(); paused = true; playing = false; handler.removeCallbacks(pump); track.pause(); abandon.run(); event("pause", Collections.emptyMap());
    }
    void resume() {
        if (closed) return;
        paused = false; progressed = SystemClock.uptimeMillis(); handler.removeCallbacks(pump); pump();
    }
    void flush() {
        if (closed) return;
        observe(); handler.removeCallbacks(pump); track.pause(); track.flush(); queue.flush(); playing = false;
        abandon.run(); progressed = SystemClock.uptimeMillis(); event("pcm_flushed", Collections.emptyMap());
    }
    void volume(float value) { if (!closed) track.setVolume(value); }
    private void fail() { if (!closed) { event("error", Collections.emptyMap()); close(); } }
    void close() {
        if (closed) return;
        closed = true; handler.removeCallbacks(pump); handler.removeCallbacks(expiry);
        try { track.pause(); track.flush(); } catch (IllegalStateException ignored) { }
        track.release(); queue.flush(); abandon.run();
    }
}
