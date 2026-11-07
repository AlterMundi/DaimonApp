package homes.dmn.interaction;

import android.content.Context;
import android.view.MotionEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import static org.junit.Assert.*;

/** Actual WebView -> origin-scoped adapter -> service/AudioTrack. No mic/provider. */
public class BeaconNativeOutputTest {
    public static final class Receipt {
        final CountDownLatch loaded = new CountDownLatch(1), done = new CountDownLatch(1);
        volatile String result;
        @JavascriptInterface public void ready() { loaded.countDown(); }
        @JavascriptInterface public void finish(String value) { result = value; done.countDown(); }
    }
    @Test public void nativeScoreUsesPlaybackHeadExpiresAndClosesWithoutBrowserAudio() throws Exception {
        Context test = InstrumentationRegistry.getInstrumentation().getContext();
        AtomicReference<android.content.SharedPreferences> preferences = new AtomicReference<>();
        AtomicReference<String> previous = new AtomicReference<>();
        AtomicReference<WebView> view = new AtomicReference<>();
        Field field = MainActivity.class.getDeclaredField("web"); field.setAccessible(true);
        Receipt receipt = new Receipt();
        String html = "<!doctype html><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><button style=\"position:fixed;inset:0;width:100%;height:100%\" onclick=\"run()\">Start synthetic Beacon</button><script src=\"assets/sonic.js\"></script><script>\n"
            + "const sleep=ms=>new Promise(r=>setTimeout(r,ms));let running=false;\n"
            + "async function run(){if(running)return;running=true;let engine;\n"
            + "try{\n"
            + " let playing=0,quiet=0,closed=0;const failures=[],open=NativeSpeechAudio.openBeacon;\n"
            + " NativeSpeechAudio.openBeacon=options=>{const owner=open({...options,onState:type=>{if(type==='beacon_playing')playing++;if(type==='beacon_quiet')quiet++;},onUnavailable:message=>failures.push(message)});const close=owner.close;owner.close=()=>{closed++;close();};return owner;};\n"
            + " // Fixture selects the prepared branch only. Production capability stays off.\n"
            + " const native={beacon:true,openBeacon:NativeSpeechAudio.openBeacon};\n"
            + " engine=ConversationSound.renderer({Native:native,Context:class{constructor(){throw Error('Unexpected browser audio');}}});\n"
            + " const vocabulary={fundamental_hz:40.4,components:{idle:1,active:2,tools:3,goal:4,pending:7,blocked:11},pulse_hz:.25,pulse_mode:'harmonic',pulse_depth:.1,peak_gain:.2,attack_ms:80,release_ms:100,max_sessions:32};\n"
            + " const frame={schema:'telecodex.sonic-state/v1',observed_at:1000,connected:true,sources:[{id:'100:1',session:1,fresh:true,observed_at:1000,execution:'working',goal_state:'active',waiting_for_human:false,tools_running:true,pending:false,error:false}]};\n"
            + " const composition=elapsed=>ConversationSound.plan(frame,vocabulary,elapsed);\n"
            + " const wait=async predicate=>{for(let n=0;n<70&&!predicate()&&!failures.length;n++)await sleep(50);if(!predicate()||failures.length)throw Error('Native condition: '+JSON.stringify({playing,quiet,failures}));};\n"
            + " if(!await engine.start())throw Error('Readiness failed');\n"
            + " engine.render(composition(19200),vocabulary);await wait(()=>playing===1);\n"
            + " const staleQuiet=quiet;for(let n=0;n<5;n++){engine.setDucking(.5);engine.setVolume(.4);await sleep(100);}\n"
            + " await wait(()=>quiet>staleQuiet);\n"
            + " // An explicit fresh observation can resume the same six native carriers.\n"
            + " engine.render(composition(0),vocabulary);await wait(()=>playing===2);\n"
            + " const captureQuiet=quiet;engine.setDucking(0);await wait(()=>quiet>captureQuiet);\n"
            + " engine.setDucking(1);await wait(()=>playing===3);\n"
            + " engine.stop();await sleep(450);if(closed!==1)throw Error('Duplicate native close');\n"
            + " if(!await engine.start())throw Error('New owner not ready');engine.render(composition(0),vocabulary);await wait(()=>playing===4);\n"
            + " NativeSpeechAudio.background(true);await sleep(100);\n"
            + " if(closed!==2)throw Error('Background retained Beacon');\n"
            + " OutputReceipt.finish('native-beacon-output');\n"
            + "}catch(e){OutputReceipt.finish(e.name+': '+e.message);}finally{engine?.stop();}}\n"
            + "OutputReceipt.ready();</script>";
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                preferences.set(activity.getPreferences(Context.MODE_PRIVATE));
                previous.set(preferences.get().getString("home", null));
                preferences.get().edit().putString("home", "https://output.invalid").commit();
                try {
                    java.lang.reflect.Method open = MainActivity.class.getDeclaredMethod("open", String.class);
                    open.setAccessible(true); open.invoke(activity, "https://output.invalid");
                } catch (Exception error) { throw new AssertionError(error); }
            });
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (view.get() == null && System.nanoTime() < deadline) {
                scenario.onActivity(activity -> { try { view.set((WebView)field.get(activity)); } catch (Exception error) { throw new AssertionError(error); } });
                if (view.get() == null) Thread.sleep(50);
            }
            assertNotNull("Host WebView initialized", view.get());
            scenario.onActivity(activity -> {
                WebView web = view.get();web.stopLoading();web.getSettings().setBlockNetworkLoads(true);
                web.addJavascriptInterface(receipt, "OutputReceipt");WebViewClient navigationOwner = web.getWebViewClient();
                web.setWebViewClient(new WebViewClient() {
                    @Override public void onPageStarted(WebView page, String url, android.graphics.Bitmap icon) {
                        navigationOwner.onPageStarted(page, url, icon);
                    }
                    @Override public WebResourceResponse shouldInterceptRequest(WebView page, WebResourceRequest request) {
                        String path=request.getUrl().getPath();
                        try {
                            if ("/interaction/".equals(path)) return new WebResourceResponse("text/html", "UTF-8",
                                new java.io.ByteArrayInputStream(html.getBytes(StandardCharsets.UTF_8)));
                            if ("/interaction/assets/sonic.js".equals(path))
                                return new WebResourceResponse("application/javascript", "UTF-8", test.getAssets().open(path.substring(path.lastIndexOf('/')+1)));
                            return new WebResourceResponse("text/plain", "UTF-8", new java.io.ByteArrayInputStream(new byte[0]));
                        } catch (Exception error) { throw new AssertionError(error); }
                    }
                });web.loadUrl("https://output.invalid/interaction/");
            });
            assertTrue("Synthetic page loaded", receipt.loaded.await(8, TimeUnit.SECONDS));
            scenario.onActivity(activity -> {
                WebView web=view.get();long now=android.os.SystemClock.uptimeMillis();
                MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,web.getWidth()/2f,web.getHeight()/2f,0);
                MotionEvent up=MotionEvent.obtain(now,now+50,MotionEvent.ACTION_UP,web.getWidth()/2f,web.getHeight()/2f,0);
                try { web.dispatchTouchEvent(down);web.dispatchTouchEvent(up); } finally { down.recycle();up.recycle(); }
            });
            assertTrue("WebView output completed: " + receipt.result, receipt.done.await(18, TimeUnit.SECONDS));
            assertEquals("native-beacon-output", receipt.result);
        } finally {
            if (preferences.get()!=null) {
                if(previous.get()==null)preferences.get().edit().remove("home").commit();
                else preferences.get().edit().putString("home",previous.get()).commit();
            }
        }
    }
}
