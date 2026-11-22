package homes.dmn.interaction;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import java.lang.reflect.Field;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import static org.junit.Assert.*;

/** Real WebView capture and origin-scoped PCM bridge, emulator only; no upload/provider/archive. */
public class MicrophoneCaptureTest {
    public static final class Receipt {
        final CountDownLatch done = new CountDownLatch(1);
        volatile String result, permission;
        @JavascriptInterface public void finish(String value) { result = value; done.countDown(); }
    }

    @Test public void grantedAndroidPermissionOpensWebViewMicrophone() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("Chromium input-device permission", PackageManager.PERMISSION_GRANTED,
            context.checkSelfPermission(Manifest.permission.MODIFY_AUDIO_SETTINGS));
        InstrumentationRegistry.getInstrumentation().getUiAutomation()
            .grantRuntimePermission(context.getPackageName(), Manifest.permission.RECORD_AUDIO);
        assertEquals(PackageManager.PERMISSION_GRANTED, context.checkSelfPermission(Manifest.permission.RECORD_AUDIO));
        AtomicReference<android.content.SharedPreferences> preferences = new AtomicReference<>();
        AtomicReference<String> previous = new AtomicReference<>();
        Field field = MainActivity.class.getDeclaredField("web"); field.setAccessible(true);
        Receipt receipt = new Receipt();
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            AtomicReference<WebView> view = new AtomicReference<>();
            scenario.onActivity(activity -> {
                // Activity.getPreferences uses getLocalClassName, not a guessed preference filename.
                preferences.set(activity.getPreferences(Context.MODE_PRIVATE));
                previous.set(preferences.get().getString("home", null));
                preferences.get().edit().putString("home", "https://capture.invalid").commit();
                try {
                    java.lang.reflect.Method open = MainActivity.class.getDeclaredMethod("open", String.class);
                    open.setAccessible(true); open.invoke(activity, "https://capture.invalid");
                } catch (Exception error) { throw new AssertionError(error); }
            });
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (view.get() == null && System.nanoTime() < deadline) {
                scenario.onActivity(activity -> { try { view.set((WebView)field.get(activity)); } catch (Exception error) { throw new AssertionError(error); } });
                if (view.get() == null) Thread.sleep(50);
            }
            assertNotNull("Host WebView initialized", view.get());
            scenario.onActivity(activity -> {
                WebView web = view.get(); web.stopLoading(); web.getSettings().setBlockNetworkLoads(true);
                web.addJavascriptInterface(receipt, "CaptureReceipt");
                android.webkit.WebChromeClient permissionOwner = web.getWebChromeClient();
                web.setWebChromeClient(new android.webkit.WebChromeClient() {
                    @Override public void onPermissionRequest(android.webkit.PermissionRequest request) {
                        receipt.permission = "page=" + web.getUrl() + ", origin=" + request.getOrigin();
                        permissionOwner.onPermissionRequest(request);
                    }
                });
                String html = "<!doctype html><script>" +
                    "(async()=>{let stream;try{stream=await navigator.mediaDevices.getUserMedia({audio:true,video:false});" +
                    "const recorder=new MediaRecorder(stream);let bytes=0;recorder.ondataavailable=e=>bytes+=e.data.size;" +
                    "recorder.onstop=async()=>{stream.getTracks().forEach(t=>t.stop());let output,deadline;try{" +
                    "if(!bytes)throw Error('Empty recording');if(!NativeSpeechAudio?.pcm)throw Error('Missing native PCM adapter');" +
                    "let played=0,complete,failed;const ended=new Promise((yes,no)=>{complete=yes;failed=no;});" +
                    "deadline=setTimeout(()=>failed(Error('Native PCM completion timed out')),8000);" +
                    "output=NativeSpeechAudio.openPcm({onProgress:(id,count)=>{played=count;},onBufferEnded:()=>complete(),onUnavailable:reason=>failed(Error(reason))});" +
                    "await output.ready;const raw=new Uint8Array(24000);for(let n=0;n<12000;n++){const v=Math.round(Math.sin(2*Math.PI*440*n/24000)*4096);raw[n*2]=v&255;raw[n*2+1]=(v>>8)&255;}" +
                    "await output.append('11111111-1111-4111-8111-111111111111',raw.length,raw);await ended;" +
                    "if(played!==raw.length)throw Error('Native frame-head position mismatch');CaptureReceipt.finish('recorded-native-pcm');" +
                    "}catch(e){CaptureReceipt.finish(e.name+': '+e.message);}finally{clearTimeout(deadline);output?.close();}};" +
                    "recorder.start();setTimeout(()=>recorder.stop(),350);" +
                    "}catch(e){stream?.getTracks().forEach(t=>t.stop());CaptureReceipt.finish(e.name+': '+e.message);}})();" +
                    "</script>";
                android.webkit.WebViewClient navigationOwner = web.getWebViewClient();
                web.setWebViewClient(new android.webkit.WebViewClient() {
                    @Override public void onPageStarted(WebView page, String url, android.graphics.Bitmap icon) {
                        navigationOwner.onPageStarted(page, url, icon);
                    }
                    @Override public android.webkit.WebResourceResponse shouldInterceptRequest(WebView page, android.webkit.WebResourceRequest request) {
                        String body = request.getUrl().toString().equals("https://capture.invalid/interaction/") ? html : "";
                        return new android.webkit.WebResourceResponse("text/html", "UTF-8",
                            new java.io.ByteArrayInputStream(body.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                    }
                });
                // Use a real HTTPS navigation: loadDataWithBaseURL has different navigation/history semantics.
                web.loadUrl("https://capture.invalid/interaction/");
            });
            assertTrue("Capture completed: " + receipt.result, receipt.done.await(15, TimeUnit.SECONDS));
            assertNotNull("Actual host permission callback", receipt.permission);
            assertEquals("Actual WebView capture; " + receipt.permission, "recorded-native-pcm", receipt.result);
        } finally {
            if (preferences.get() != null) {
                if (previous.get() == null) preferences.get().edit().remove("home").commit();
                else preferences.get().edit().putString("home", previous.get()).commit();
            }
        }
    }
}
