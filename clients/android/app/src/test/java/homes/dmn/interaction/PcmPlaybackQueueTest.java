package homes.dmn.interaction;

import org.junit.Test;
import static org.junit.Assert.*;
import java.util.UUID;

public class PcmPlaybackQueueTest {
    private final String first = UUID.randomUUID().toString(), second = UUID.randomUUID().toString();
    private void append(PcmPlaybackQueue q, int sequence, String id, int end, int size) throws Exception {
        byte[] data = new byte[size]; q.append(sequence, id, end, data, VerifiedAudioBuffer.hash(data));
    }
    @Test public void partialWritesAndQueuedBuffersNeverBecomePlayed() throws Exception {
        PcmPlaybackQueue q = new PcmPlaybackQueue(); append(q, 0, first, 8, 8); append(q, 1, second, 4, 4);
        assertEquals(12, q.queued()); q.wrote(4); assertEquals(4, q.submitted());
        assertThrows(IllegalArgumentException.class, () -> q.advance(6));
        assertEquals(Integer.valueOf(2), q.advance(2).get(first)); assertFalse(q.advance(2).containsKey(second));
        q.wrote(4); assertEquals(4, q.next().buffer.remaining()); q.wrote(4);
        assertEquals(Integer.valueOf(8), q.advance(8).get(first)); assertEquals(Integer.valueOf(2), q.advance(10).get(second));
        assertEquals(Integer.valueOf(4), q.advance(12).get(second)); assertEquals(0, q.queued()); assertNull(q.next());
    }
    @Test public void sourceOffsetsSurviveChunkBoundariesButRetireOnFlush() throws Exception {
        PcmPlaybackQueue q = new PcmPlaybackQueue(); append(q, 0, first, 4, 4); q.wrote(4); q.advance(4);
        append(q, 1, first, 8, 4); q.wrote(4); assertEquals(Integer.valueOf(6), q.advance(6).get(first));
        q.flush(); assertEquals(0, q.queued()); assertNull(q.next());
        assertThrows(IllegalArgumentException.class, () -> append(q, 2, first, 12, 4));
        append(q, 2, second, 4, 4); q.wrote(4); assertEquals(Integer.valueOf(2), q.advance(2).get(second));
    }
    @Test public void integritySequenceOddPcmAndContinuityFailBeforeRetention() throws Exception {
        PcmPlaybackQueue q = new PcmPlaybackQueue();
        assertThrows(IllegalArgumentException.class, () -> append(q, 1, first, 4, 4));
        assertThrows(IllegalArgumentException.class, () -> append(q, 0, first, 4, 3));
        assertThrows(IllegalArgumentException.class, () -> append(q, 0, first, 8, 4));
        assertThrows(IllegalArgumentException.class, () -> q.append(0, first, 4, new byte[4], "0".repeat(64)));
        assertEquals(0, q.queued()); append(q, 0, first, 4, 4);
    }
    @Test public void queueAndSessionBoundsCannotBeRenewedByFlush() throws Exception {
        PcmPlaybackQueue q = new PcmPlaybackQueue(); int sequence = 0, end = 0;
        while (q.queued() + 32000 <= PcmPlaybackQueue.MAX_QUEUED) { end += 32000; append(q, sequence++, first, end, 32000); }
        final int next = sequence, ending = end;
        assertThrows(IllegalArgumentException.class, () -> append(q, next, first, ending + 32000, 32000));
        int lifetime = end;
        // Flush discards bytes but does not reset the five-minute session budget.
        for (int n = 0; n < 12; n++) {
            q.flush(); String id = UUID.randomUUID().toString(); int source = 0;
            while (lifetime + 32000 <= PcmPlaybackQueue.MAX_SESSION && q.queued() + 32000 <= PcmPlaybackQueue.MAX_QUEUED) {
                source += 32000; append(q, sequence++, id, source, 32000); lifetime += 32000;
            }
        }
        q.flush(); final int finalSequence = sequence;
        assertThrows(IllegalArgumentException.class, () -> append(q, finalSequence, UUID.randomUUID().toString(), 32000, 32000));
    }
}
