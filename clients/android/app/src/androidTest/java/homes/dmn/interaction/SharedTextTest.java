package homes.dmn.interaction;

import android.content.ClipData;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import java.lang.reflect.Field;
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
    @Test public void actualActivityNewIntentAndRecreationPreservePendingIdentityAndDestination() {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue("Synthetic debug APK only", (context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        // Only this isolated CI app's setup selection, not any production login.
        context.getSharedPreferences("MainActivity", Context.MODE_PRIVATE).edit().remove("home").commit();
        context.getSharedPreferences("homes.dmn.interaction.MainActivity", Context.MODE_PRIVATE).edit().remove("home").commit();
        Intent launch = new Intent(context, MainActivity.class).setAction(Intent.ACTION_SEND)
            .setType("text/plain").putExtra(Intent.EXTRA_TEXT, "Synthetic cold-start share");
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(launch)) {
            String[] ident = new String[1];
            scenario.onActivity(activity -> {
                assertNull(field(activity, "web")); // setup only; no network or login fixture.
                assertNotNull(field(activity, "incomingShare"));
                // Complete only the synthetic offer in this fixture. Keep the
                // actual ActivityScenario action/type/component when delivering
                // the next Intent; its lifecycle monitor uses filterEquals.
                setField(activity, "incomingShare", null);
                activity.onNewIntent(new Intent(activity.getIntent()).putExtra(Intent.EXTRA_TEXT, "Synthetic incoming URL https://example.test"));
                SharedText pending = (SharedText)field(activity, "incomingShare"); assertNotNull(pending); ident[0] = pending.id;
                setField(activity, "shareHome", "https://example.test");
                setField(activity, "shareBinding", "synthetic-owner");
            });
            scenario.recreate();
            scenario.onActivity(activity -> {
                SharedText pending = (SharedText)field(activity, "incomingShare");
                assertNotNull(pending); assertEquals(ident[0], pending.id);
                assertEquals("https://example.test", field(activity, "shareHome"));
                assertEquals("synthetic-owner", field(activity, "shareBinding"));
                assertNull(field(activity, "web"));
            });
        }
    }
    private Object field(MainActivity activity, String name) {
        try { Field f = MainActivity.class.getDeclaredField(name); f.setAccessible(true); return f.get(activity); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private void setField(MainActivity activity, String name, Object value) {
        try { Field f = MainActivity.class.getDeclaredField(name); f.setAccessible(true); f.set(activity, value); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private void refuse(Intent intent) {
        try { SharedText.from(intent); fail("Unsupported share must be refused"); }
        catch (IllegalArgumentException expected) { }
    }
}
