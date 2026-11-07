package homes.dmn.interaction;

/** Six phase-continuous sine carriers. Called only by the owning audio worker. */
final class BeaconSynth {
    static final int TONES = 6;
    private static final double TAU = 2 * Math.PI;
    private final int sampleRate;
    private final double[] frequencies, pulses, phase = new double[TONES], pulsePhase = new double[TONES];
    private final double[] weight = new double[TONES], target = new double[TONES], step = new double[TONES];
    private final double pulseDepth;
    private int weightFrames, gainFrames;
    private double gain, targetGain, gainStep;

    BeaconSynth(int sampleRate, double[] frequencies, double[] pulses, double pulseDepth) {
        if (sampleRate < 24000 || sampleRate > 96000 || frequencies == null || pulses == null
            || frequencies.length != TONES || pulses.length != TONES
            || !finite(pulseDepth, 0, .5)) throw new IllegalArgumentException("Invalid Beacon configuration");
        for (int i = 0; i < TONES; i++) {
            if (!finite(frequencies[i], 20, 16384) || !finite(pulses[i], 0, 64))
                throw new IllegalArgumentException("Invalid Beacon carrier");
        }
        this.sampleRate = sampleRate; this.frequencies = frequencies.clone(); this.pulses = pulses.clone();
        this.pulseDepth = pulseDepth;
    }
    private static boolean finite(double value, double minimum, double maximum) {
        return Double.isFinite(value) && value >= minimum && value <= maximum;
    }
    private int frames(int milliseconds) {
        if (milliseconds < 0 || milliseconds > 2000) throw new IllegalArgumentException("Invalid Beacon transition");
        return (int)((long)sampleRate * milliseconds / 1000);
    }
    void weights(double[] next, int milliseconds) {
        int frames = frames(milliseconds);
        if (next == null || next.length != TONES) throw new IllegalArgumentException("Invalid Beacon weights");
        double sum = 0; boolean changed = false;
        for (int i = 0; i < TONES; i++) {
            if (!finite(next[i], 0, 1) || next[i] > 0 && frequencies[i] >= sampleRate * .45)
                throw new IllegalArgumentException("Invalid Beacon weight or sample-rate limit");
            sum += next[i]; changed |= next[i] != target[i];
        }
        if (sum > 1 + 1e-9) throw new IllegalArgumentException("Beacon weights exceed normalized mix");
        if (!changed) return; // Fresh observations cannot restart a running envelope.
        weightFrames = frames;
        for (int i = 0; i < TONES; i++) {
            target[i] = next[i]; step[i] = frames == 0 ? 0 : (next[i] - weight[i]) / frames;
            if (frames == 0) weight[i] = next[i];
        }
    }
    void gain(double next, int milliseconds) {
        int frames = frames(milliseconds);
        if (!finite(next, 0, .8)) throw new IllegalArgumentException("Invalid Beacon level");
        if (next == targetGain) return;
        targetGain = next; gainFrames = frames; gainStep = frames == 0 ? 0 : (next - gain) / frames;
        if (frames == 0) gain = next;
    }
    void render(short[] output, int offset, int count) {
        if (output == null || offset < 0 || count < 0 || offset > output.length - count)
            throw new IllegalArgumentException("Invalid Beacon output window");
        for (int n = offset; n < offset + count; n++) {
            if (weightFrames > 0) {
                weightFrames--;
                for (int i = 0; i < TONES; i++) weight[i] = weightFrames == 0 ? target[i] : weight[i] + step[i];
            }
            if (gainFrames > 0) { gainFrames--; gain = gainFrames == 0 ? targetGain : gain + gainStep; }
            double value = 0;
            for (int i = 0; i < TONES; i++) {
                double breath = pulses[i] == 0 ? 1 : 1 - pulseDepth + pulseDepth * Math.sin(pulsePhase[i]);
                value += weight[i] * Math.sin(phase[i]) * breath;
                phase[i] += TAU * frequencies[i] / sampleRate;
                pulsePhase[i] += TAU * pulses[i] / sampleRate;
                if (phase[i] >= TAU) phase[i] -= TAU;
                if (pulsePhase[i] >= TAU) pulsePhase[i] -= TAU;
            }
            output[n] = (short)Math.round(Math.max(-1, Math.min(1, value * gain)) * 32767);
        }
    }
}
