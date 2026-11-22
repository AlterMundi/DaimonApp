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
public class WebRtcNativeOutputTest {
    public static final class Receipt {
        final CountDownLatch loaded = new CountDownLatch(1), done = new CountDownLatch(1);
        volatile String result;
        @JavascriptInterface public void ready() { loaded.countDown(); }
        @JavascriptInterface public void finish(String value) { result = value; done.countDown(); }
    }
    @Test public void remoteStreamConversionUsesRealNativePlaybackAndRetiresPausedAudio() throws Exception {
        Context test = InstrumentationRegistry.getInstrumentation().getContext();
        AtomicReference<android.content.SharedPreferences> preferences = new AtomicReference<>();
        AtomicReference<String> previous = new AtomicReference<>();
        AtomicReference<WebView> view = new AtomicReference<>();
        Field field = MainActivity.class.getDeclaredField("web"); field.setAccessible(true);
        Receipt receipt = new Receipt();
        String html = "<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>" +
            "<button style='position:fixed;inset:0;width:100%;height:100%' onclick='run()'>Start synthetic audio</button>" +
            "<script src='assets/webrtc-native-audio.js'></script><script>" +
            "const sleep=ms=>new Promise(r=>setTimeout(r,ms));let running=false;" +
            "async function run(){if(running)return;running=true;let source,osc,out;" +
            "try{let writes=0,played=0,closes=0;const failures=[],open=NativeSpeechAudio.openPcm;" +
            "NativeSpeechAudio.openPcm=options=>{if(options.sessionSeconds!==600)throw Error('Wrong lifetime');" +
            "const driver=open({...options,onProgress:(id,count)=>{played+=count;}});" +
            "const append=driver.append.bind(driver),close=driver.close.bind(driver);" +
            "driver.append=(...args)=>{writes++;return append(...args);};driver.close=()=>{closes++;close();};return driver;};" +
            "source=new AudioContext({sampleRate:48000});const stream=source.createMediaStreamDestination();" +
            "osc=source.createOscillator();osc.connect(stream);osc.start();await source.resume();" +
            "out=await WebRtcNativeAudio.open({onUnavailable:m=>failures.push(m)});out.attach(stream.stream);" +
            "for(let n=0;n<40&&played===0&&!failures.length;n++)await sleep(100);" +
            "if(!played||!writes)throw Error('No actual native frame-head progress');" +
            "out.pause();const before=writes;await sleep(300);if(writes!==before)throw Error('Paused output was appended');" +
            "const paused=played;out.resume();for(let n=0;n<30&&played===paused&&!failures.length;n++)await sleep(100);" +
            "if(played===paused||writes<=before)throw Error('Fresh native output did not resume');" +
            "out.close();out.close();const ended=writes;await sleep(200);" +
            "if(writes!==ended||closes!==1||failures.length)throw Error('Output cleanup: '+JSON.stringify({writes,ended,closes,failures}));" +
            "OutputReceipt.finish('native-webview-output');" +
            "}catch(e){OutputReceipt.finish(e.name+': '+e.message);}finally{out?.close();osc?.stop();if(source)await source.close();}}" +
            "OutputReceipt.ready();</script>";
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
                            if ("/interaction/assets/webrtc-native-audio.js".equals(path) || "/interaction/assets/voice-output-pcm.js".equals(path))
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
            assertTrue("WebView output completed: " + receipt.result, receipt.done.await(15, TimeUnit.SECONDS));
            assertEquals("native-webview-output", receipt.result);
        } finally {
            if (preferences.get()!=null) {
                if(previous.get()==null)preferences.get().edit().remove("home").commit();
                else preferences.get().edit().putString("home",previous.get()).commit();
            }
        }
    }
}
