package homes.dmn.interaction;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Arrays;
import java.util.function.Consumer;

/** One foreground Beacon worker; latest controls replace, rather than queue, data. */
final class BeaconOutput {
    private static final int RATE = 24000, QUANTUM = 960;
    private static final long LIFETIME = 2 * 60 * 60 * 1000L;
    static final class Frame {
        final double[] frequencies, pulses, weights;
        final double depth, level;
        final int transition;
        final long expires;
        Frame(JSONObject value) throws Exception {
            frequencies = vector(value.getJSONArray("frequencies"), 20, 16384);
            pulses = vector(value.getJSONArray("pulses"), 0, 64);
            weights = vector(value.getJSONArray("weights"), 0, 1);
            double sum = 0;
            for (int i = 0; i < 6; i++) {
                sum += weights[i];
                if (weights[i] > 0 && frequencies[i] >= RATE * .45)
                    throw new IllegalArgumentException("Beacon carrier exceeds sample rate");
            }
            if (sum > 1 + 1e-9) throw new IllegalArgumentException("Beacon mix exceeds normalized budget");
            depth = number(value.get("depth"), 0, .5);
            level = number(value.get("level"), 0, .8);
            transition = integer(value.get("transition_ms"), 20, 2000);
            double deadline = number(value.get("expires_at_ms"), 0, SystemClock.elapsedRealtime() + 20000);
            if (deadline != Math.rint(deadline)) throw new IllegalArgumentException("Beacon expiry must be an integer");
            expires = (long)deadline;
        }
        boolean sameConfiguration(Frame other) {
            return depth == other.depth && Arrays.equals(frequencies, other.frequencies) && Arrays.equals(pulses, other.pulses);
        }
    }
    private static double number(Object value, double minimum, double maximum) {
        if (!(value instanceof Number)) throw new IllegalArgumentException("Beacon value must be numeric");
        double n = ((Number)value).doubleValue();
        if (!Double.isFinite(n) || n < minimum || n > maximum) throw new IllegalArgumentException("Beacon value out of bounds");
        return n;
    }
    private static int integer(Object value, int minimum, int maximum) {
        double n = number(value, minimum, maximum);
        if (n != Math.rint(n)) throw new IllegalArgumentException("Beacon bound must be an integer");
        return (int)n;
    }
    private static double[] vector(JSONArray values, double minimum, double maximum) throws Exception {
        if (values.length() != 6) throw new IllegalArgumentException("Beacon requires six components");
        double[] result = new double[6];
        for (int i = 0; i < 6; i++) result[i] = number(values.get(i), minimum, maximum);
        return result;
    }
    private final Object guard = new Object();
    private final HandlerThread thread = new HandlerThread("Daimon-Beacon");
    private final Handler worker, main;
    private final Consumer<JSONObject> emit;
    private final long deadline = SystemClock.elapsedRealtime() + LIFETIME;
    private final short[] buffer = new short[QUANTUM];
    private final Runnable pump = this::pump;
    private Frame pendingFrame, configuration;
    private double[] pendingGain;
    private int stopMilliseconds = -1;
    private boolean running, scheduled, terminated;
    private long control, appliedControl;
    // Fields below belong to the audio worker only.
    private AudioTrack track;
    private BeaconSynth synth;
    private int offset = QUANTUM;
    private boolean playing, stale = true, reportedPlaying, reportedQuiet;
    private long validUntil, lastHead, progressAt, submitted;
    private int appliedStop = -1;

    BeaconOutput(Handler main, Consumer<JSONObject> emit) {
        this.main = main; this.emit = emit;
        thread.start(); worker = new Handler(thread.getLooper());
        synchronized (guard) { schedule(0); }
    }
    boolean stopping() { synchronized (guard) { return stopMilliseconds >= 0 || terminated; } }
    long frame(Frame value) {
        synchronized (guard) {
            if (stopMilliseconds >= 0 || terminated) return -1;
            control = Math.incrementExact(control);
            pendingFrame = value; pendingGain = new double[]{value.level, 120}; schedule(0);
            return control;
        }
    }
    long level(JSONObject value) throws Exception {
        double gain = number(value.get("level"), 0, .8);
        int milliseconds = integer(value.get("transition_ms"), 0, 2000);
        synchronized (guard) {
            if (stopMilliseconds >= 0 || terminated) return -1;
            control = Math.incrementExact(control);
            pendingGain = new double[]{gain, milliseconds}; schedule(0);
            return control;
        }
    }
    void close(boolean fade) {
        synchronized (guard) {
            if (terminated) return;
            int next = fade ? 350 : 0;
            stopMilliseconds = stopMilliseconds < 0 ? next : Math.min(stopMilliseconds, next);
            pendingFrame = null; pendingGain = null; schedule(0);
        }
    }
    // Caller holds guard. At most one queued pump and one latest frame/level.
    private void schedule(long delay) {
        if (terminated || running) return;
        if (scheduled) worker.removeCallbacks(pump);
        scheduled = true; worker.postDelayed(pump, delay);
    }
    private void event(String type, long frames) {
        long observedControl = appliedControl;
        long observedClock = SystemClock.elapsedRealtime();
        main.post(() -> {
            try { emit.accept(new JSONObject().put("type", type).put("played_frames", frames)
                .put("control", observedControl).put("clock_ms", observedClock)); }
            catch (Exception ignored) { /* Observation cannot crash the audio worker. */ }
        });
    }
    private void finish(String reason) {
        synchronized (guard) { if (terminated) return; terminated = true; pendingFrame = null; pendingGain = null; }
        String outcome = reason;
        try {
            if (track != null) {
                try { track.pause(); track.flush(); } catch (IllegalStateException ignored) { }
                track.release(); track = null;
            }
        } catch (RuntimeException error) {
            outcome = "beacon_error";
        } finally {
            event(outcome, lastHead); thread.quitSafely();
        }
    }
    private void pump() {
        Frame next; double[] gain; int stopping;
        synchronized (guard) {
            scheduled = false; if (terminated) return; running = true;
            next = pendingFrame; pendingFrame = null; gain = pendingGain; pendingGain = null; stopping = stopMilliseconds;
            if (next != null || gain != null) appliedControl = control;
        }
        long delay = 10;
        try {
            long now = SystemClock.elapsedRealtime();
            if (now >= deadline) { finish("beacon_closed"); return; }
            if (now >= deadline - 350 && stopping < 0) { close(true); stopping = (int)Math.max(0, deadline - now); }
            if (stopping == 0) { finish("beacon_closed"); return; }
            if (track == null) {
                int minimum = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
                if (minimum < 1 || minimum > 9600) throw new IllegalStateException("Beacon output unavailable");
                track = new AudioTrack.Builder()
                    .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                    .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(minimum, QUANTUM * 4)).build();
                if (track.getState() != AudioTrack.STATE_INITIALIZED) throw new IllegalStateException("Beacon output unavailable");
                validUntil = now + 20000; event("beacon_ready", 0);
            }
            if (next != null && stopping < 0) {
                if (configuration == null) { configuration = next; synth = new BeaconSynth(RATE, next.frequencies, next.pulses, next.depth); }
                else if (!configuration.sameConfiguration(next)) throw new IllegalArgumentException("Beacon vocabulary changed");
                validUntil = next.expires; stale = false; synth.weights(next.weights, next.transition);
            }
            if (gain != null && synth != null && stopping < 0) synth.gain(gain[0], (int)gain[1]);
            if (synth != null && stopping >= 0 && appliedStop != stopping) {
                appliedStop = stopping; synth.gain(0, stopping);
            }
            if (synth != null && now >= validUntil && !stale) { stale = true; synth.weights(new double[6], 1000); }
            if (synth == null) {
                if (stopping >= 0) { finish("beacon_closed"); return; }
                delay = Math.min(20000, deadline - now - 350); return;
            }
            if (offset == QUANTUM && !synth.silent()) { synth.render(buffer, 0, QUANTUM); offset = 0; }
            if (offset < QUANTUM) {
                int count = track.write(buffer, offset, QUANTUM - offset, AudioTrack.WRITE_NON_BLOCKING);
                if (count < 0) throw new IllegalStateException("Beacon device write failed");
                offset += count; submitted += count;
                if (!playing && count > 0) { track.play(); playing = true; progressAt = now; lastHead = 0; }
            }
            if (playing) {
                long head = Integer.toUnsignedLong(track.getPlaybackHeadPosition());
                if (head != lastHead) { lastHead = head; progressAt = now; }
                if (head > 0 && !reportedPlaying) { reportedPlaying = true; event("beacon_playing", head); }
                if (now - progressAt > 2000) throw new IllegalStateException("Beacon device stalled");
                if (synth.silent() && offset == QUANTUM && head >= submitted) {
                    track.pause(); track.flush(); playing = reportedPlaying = false; submitted = lastHead = 0;
                }
            }
            if (!playing && synth.silent()) {
                if (!reportedQuiet) { reportedQuiet = true; event("beacon_quiet", lastHead); }
                if (stopping >= 0) { finish("beacon_closed"); return; }
                delay = Math.max(1, deadline - now - 350);
            } else reportedQuiet = false;
        } catch (Exception error) { finish("beacon_error"); }
        finally {
            synchronized (guard) {
                running = false;
                if (!terminated) schedule(pendingFrame != null || pendingGain != null || stopMilliseconds != appliedStop && stopMilliseconds >= 0 ? 0 : delay);
            }
        }
    }
}
