package homes.dmn.interaction;

import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import org.junit.Test;
import static org.junit.Assert.*;

/** Real Android Intent/Bundle parsing; no user content, WebView login or send. */
public class SharedTextTest {
    @Test public void plainTextAndUrlSurviveRecreationWithOneIdentity() {
        String text = "An existing draft stays separate.\nhttps://example.test/a?x=1&y=2\n<svg> 🧭";
        SharedText original = SharedText.from(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text));
        assertNotNull(original); assertEquals(text, original.text);
        Bundle state = new Bundle(); original.save(state); SharedText reopened = SharedText.restore(state);
        assertNotNull(reopened); assertEquals(original.id, reopened.id); assertEquals(text, reopened.text);
        assertNull(SharedText.from(new Intent(Intent.ACTION_MAIN)));
        assertNull(SharedText.restore(new Bundle()));
    }
    @Test public void binaryOrOversizedInputIsNotSilentlyTruncatedToText() {
        refuse(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, " "));
        refuse(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "🧭".repeat(4000)));
        refuse(new Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_TEXT, "caption"));
        refuse(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "caption").putExtra(Intent.EXTRA_STREAM, Uri.parse("content://example.test/photo")));
        Intent hidden = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "caption");
        ClipData clips = ClipData.newPlainText("text", "caption"); clips.addItem(new ClipData.Item(Uri.parse("content://example.test/photo"))); hidden.setClipData(clips); refuse(hidden);
    }
    private void refuse(Intent intent) {
        try { SharedText.from(intent); fail("Unsupported share must be refused"); }
        catch (IllegalArgumentException expected) { }
    }
}
