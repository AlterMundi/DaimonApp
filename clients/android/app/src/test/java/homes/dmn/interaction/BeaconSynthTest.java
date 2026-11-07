package homes.dmn.interaction;

import org.junit.Test;
import static org.junit.Assert.*;
import java.util.Arrays;

public class BeaconSynthTest {
    private final double[] frequencies = {40.4, 80.8, 121.2, 161.6, 282.8, 444.4};
    private BeaconSynth synth() { return new BeaconSynth(24000, frequencies, new double[6], 0); }
    private double amplitude(short[] pcm, double hz) {
        double sine = 0, cosine = 0;
        for (int i = 0; i < pcm.length; i++) {
            sine += pcm[i] / 32767.0 * Math.sin(2 * Math.PI * hz * i / 24000);
            cosine += pcm[i] / 32767.0 * Math.cos(2 * Math.PI * hz * i / 24000);
        }
        return 2 * Math.hypot(sine, cosine) / pcm.length;
    }
    @Test public void exactBeaconSeriesHasNoInventedPartialsOrTexture() {
        BeaconSynth synth = synth(); synth.weights(new double[]{1, 0, 0, 0, 0, 0}, 0); synth.gain(.6, 0);
        short[] pcm = new short[120000]; synth.render(pcm, 0, pcm.length);
        assertEquals(.6, amplitude(pcm, 40.4), .0001);
        for (double hz : new double[]{18, 65, 80.8, 121.2, 161.6, 202, 282.8, 444.4})
            assertTrue("Unexpected partial at " + hz, amplitude(pcm, hz) < .0001);
    }
    @Test public void simultaneousComponentsStayInsideOneNormalizedBudget() {
        BeaconSynth synth = synth(); double[] weights = new double[6]; Arrays.fill(weights, 1.0 / 6);
        synth.weights(weights, 0); synth.gain(.6, 0);
        short[] pcm = new short[120000]; synth.render(pcm, 0, pcm.length);
        for (double hz : frequencies) assertEquals(.1, amplitude(pcm, hz), .0001);
        for (short value : pcm) assertTrue(Math.abs((int)value) <= Math.ceil(.6 * 32767));
    }
    @Test public void chunkingAndRepeatedObservationsNeverResetCarriersOrEnvelopes() {
        BeaconSynth whole = synth(), chunks = synth();
        double[] first = {1, 0, 0, 0, 0, 0}; whole.weights(first, 1000); chunks.weights(first, 1000);
        whole.gain(.6, 120); chunks.gain(.6, 120);
        short[] a = new short[48000], b = new short[a.length]; whole.render(a, 0, a.length);
        for (int offset = 0; offset < b.length; offset += 137) {
            chunks.weights(first, 1000); chunks.gain(.6, 120);
            chunks.render(b, offset, Math.min(137, b.length - offset));
        }
        assertArrayEquals(a, b);
    }
    @Test public void harmonicBreathingUsesOnlyTheSpecifiedAmplitudeEnvelope() {
        BeaconSynth synth = new BeaconSynth(24000, frequencies, new double[]{.25, .5, .75, 1, 1.75, 2.75}, .25);
        synth.weights(new double[]{1, 0, 0, 0, 0, 0}, 0); synth.gain(.6, 0);
        short[] pcm = new short[24000]; synth.render(pcm, 0, pcm.length);
        for (int i = 0; i < pcm.length; i++) {
            double time = i / 24000.0;
            long expected = Math.round(32767 * .6 * Math.sin(2 * Math.PI * 40.4 * time)
                * (.75 + .25 * Math.sin(2 * Math.PI * .25 * time)));
            assertEquals(expected, pcm[i], 1);
        }
    }
    @Test public void transitionsRetargetCurrentValuesAndFinishSilent() {
        BeaconSynth synth = synth(); synth.weights(new double[]{1, 0, 0, 0, 0, 0}, 0); synth.gain(.6, 0);
        short[] pcm = new short[2400]; synth.render(pcm, 0, pcm.length);
        for (int n = 0; n < 10; n++) {
            synth.weights(n % 2 == 0 ? new double[]{0, 1, 0, 0, 0, 0} : new double[]{1, 0, 0, 0, 0, 0}, 1000);
            synth.render(pcm, 0, pcm.length);
            for (short value : pcm) assertTrue(Math.abs((int)value) <= Math.ceil(.6 * 32767));
        }
        synth.gain(0, 350); short[] tail = new short[9000]; synth.render(tail, 0, tail.length);
        for (int i = 8400; i < tail.length; i++) assertEquals(0, tail[i]);
    }
    @Test public void invalidUpdatesAreAtomicAndInputsAreCopied() {
        double[] owned = frequencies.clone(); BeaconSynth valid = new BeaconSynth(24000, owned, new double[6], 0);
        owned[0] = 1000;
        BeaconSynth other = synth(); double[] first = {1, 0, 0, 0, 0, 0}; valid.weights(first, 0); other.weights(first, 0);
        valid.gain(.6, 0); other.gain(.6, 0); first[0] = 0;
        assertThrows(IllegalArgumentException.class, () -> valid.weights(new double[]{1, 1, 0, 0, 0, 0}, 100));
        assertThrows(IllegalArgumentException.class, () -> valid.gain(Double.NaN, 100));
        assertThrows(IllegalArgumentException.class, () -> valid.weights(new double[6], 2001));
        short[] a = new short[1000], b = new short[a.length]; valid.render(a, 0, a.length); other.render(b, 0, b.length);
        assertArrayEquals(a, b);
        double[] aliased = {16384, 80.8, 121.2, 161.6, 282.8, 444.4};
        BeaconSynth limited = new BeaconSynth(24000, aliased, new double[6], 0);
        assertThrows(IllegalArgumentException.class, () -> limited.weights(new double[]{1, 0, 0, 0, 0, 0}, 0));
    }
}
