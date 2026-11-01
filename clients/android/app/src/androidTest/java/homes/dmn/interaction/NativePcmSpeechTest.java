package homes.dmn.interaction;

import androidx.test.core.app.ActivityScenario;
import org.junit.Test;
import static org.junit.Assert.*;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

/** Real AudioTrack on the emulator. Synthetic PCM only; no microphone/network. */
public class NativePcmSpeechTest {
    @Test public void nativeHeadPauseFlushAndFreshUtteranceUseOneSpeechOwner() throws Exception {
        AtomicReference<SpeechOutput> output = new AtomicReference<>(); AtomicReference<String> error = new AtomicReference<>();
        ConcurrentHashMap<String,Integer> positions = new ConcurrentHashMap<>();
        AtomicInteger ready = new AtomicInteger(), ended = new AtomicInteger(), flushed = new AtomicInteger();
        String first = UUID.randomUUID().toString(), interrupted = UUID.randomUUID().toString(), fresh = UUID.randomUUID().toString();
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> output.set(new SpeechOutput(activity, new Handler(Looper.getMainLooper()), value -> {
                String type = value.optString("type");
                if (type.equals("pcm_ready")) ready.incrementAndGet();
                if (type.equals("ended")) ended.incrementAndGet();
                if (type.equals("pcm_flushed")) flushed.incrementAndGet();
                if (type.equals("error")) error.set(value.toString());
                JSONArray items = value.optJSONArray("positions");
                if (items != null) for (int n = 0; n < items.length(); n++) {
                    JSONObject item = items.optJSONObject(n);
                    if (item != null) positions.put(item.optString("utterance"), item.optInt("played_bytes"));
                }
            })));
            try {
                command(scenario, output, "pcm_begin", new JSONObject()); assertEquals(1, ready.get());
                byte[] shortTone = tone(12000); send(scenario, output, 0, first, shortTone.length, shortTone);
                await(() -> positions.getOrDefault(first, 0) > 0, error);
                command(scenario, output, "pause", new JSONObject()); int paused = positions.getOrDefault(first, 0);
                assertTrue(paused < shortTone.length); Thread.sleep(150); assertEquals(paused, (int)positions.getOrDefault(first, 0));
                command(scenario, output, "play", new JSONObject()); await(() -> positions.getOrDefault(first, 0) == shortTone.length && ended.get() > 0, error);
                byte[] longTone = tone(48000); int sequence = 1;
                for (int offset = 0; offset < longTone.length; offset += 32000) {
                    byte[] part = Arrays.copyOfRange(longTone, offset, Math.min(offset + 32000, longTone.length));
                    send(scenario, output, sequence++, interrupted, offset + part.length, part);
                }
                await(() -> positions.getOrDefault(interrupted, 0) > 0, error);
                long before = System.nanoTime(); command(scenario, output, "pcm_flush", new JSONObject());
                assertTrue("Flush cannot block the UI", (System.nanoTime() - before) / 1000000 < 2000);
                assertEquals(1, flushed.get()); assertTrue(positions.getOrDefault(interrupted, 0) < longTone.length);
                send(scenario, output, sequence++, fresh, shortTone.length, shortTone);
                await(() -> positions.getOrDefault(fresh, 0) == shortTone.length, error);
                assertNull(error.get());
                // A source retired by flush cannot return under a new chunk.
                send(scenario, output, sequence, interrupted, longTone.length + 2, new byte[2]);
                assertNotNull("Retired source must be rejected", error.get());
                assertTrue(positions.getOrDefault(interrupted, 0) < longTone.length);
            } finally { scenario.onActivity(activity -> output.get().stop()); }
        }
    }
    private byte[] tone(int samples) {
        byte[] bytes = new byte[samples * 2];
        for (int n = 0; n < samples; n++) { short value = (short)(Math.sin(2 * Math.PI * 440 * n / 24000) * 4096); bytes[n * 2] = (byte)value; bytes[n * 2 + 1] = (byte)(value >> 8); }
        return bytes;
    }
    private void await(BooleanSupplier condition, AtomicReference<String> error) throws Exception {
        long deadline = System.nanoTime() + 8000000000L;
        while (!condition.getAsBoolean() && error.get() == null && System.nanoTime() < deadline) Thread.sleep(20);
        assertNull(error.get()); assertTrue("Native playback condition timed out", condition.getAsBoolean());
    }
    private void send(ActivityScenario<MainActivity> scenario, AtomicReference<SpeechOutput> output, int sequence, String utterance, int end, byte[] bytes) throws Exception {
        command(scenario, output, "pcm_chunk", new JSONObject().put("sequence", sequence).put("utterance", utterance).put("end", end)
            .put("data", Base64.encodeToString(bytes, Base64.NO_WRAP)).put("sha256", VerifiedAudioBuffer.hash(bytes)));
    }
    private void command(ActivityScenario<MainActivity> scenario, AtomicReference<SpeechOutput> output, String type, JSONObject value) throws Exception {
        value.put("command", type).put("id", "synthetic_native_pcm"); scenario.onActivity(activity -> output.get().command(value));
    }
}
