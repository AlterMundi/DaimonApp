package homes.dmn.interaction;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.view.MotionEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.junit.Test;
import static org.junit.Assert.*;

/** Real App WebView/file chooser/content reader; synthetic private test bytes only. */
public class SharedFilePickerTest {
    public static final class Receipt {
        final CountDownLatch ready=new CountDownLatch(1), done=new CountDownLatch(1);
        volatile String result;
        @JavascriptInterface public void ready() { ready.countDown(); }
        @JavascriptInterface public void finish(String value) { result=value;done.countDown(); }
    }
    @Test public void explicitOfferPickerReadsBothGrantedOriginalsWithoutSend() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Uri one=Uri.parse("content://homes.dmn.interaction.pilot.test.saved/share-one");
        Uri two=Uri.parse("content://homes.dmn.interaction.pilot.test.saved/share-two");
        byte[] first=new byte[]{0,1,2,3,0,127}, second="Second exact shared original".getBytes(StandardCharsets.UTF_8);
        try(java.io.OutputStream out=context.getContentResolver().openOutputStream(one)){out.write(first);}
        try(java.io.OutputStream out=context.getContentResolver().openOutputStream(two)){out.write(second);}
        AtomicReference<SharedPreferences> preferences=new AtomicReference<>();AtomicReference<String> previous=new AtomicReference<>();
        AtomicReference<WebView> view=new AtomicReference<>();Receipt receipt=new Receipt();
        String html="<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
            +"<style>.native-share-offer button:first-of-type{position:fixed;inset:0;width:100%;height:100%;z-index:10}</style>"
            +"<textarea>Existing draft.</textarea><div id='compose'></div><script>"
            +"let binding='synthetic-owner',sent=0;document.addEventListener('submit',e=>{sent++;e.preventDefault();});"
            +"NativeSharedText.mount({parent:document.querySelector('#compose'),draft:document.querySelector('textarea'),getBinding:()=>binding,"
            +"onFiles:async files=>{try{const values=[];for(const f of files){const b=new Uint8Array(await f.arrayBuffer());values.push(btoa(String.fromCharCode(...b)));}"
            +"if(files.length!==2||sent!==0)throw Error('Wrong count or automatic Send');SharedReceipt.finish(JSON.stringify(values));}"
            +"catch(e){SharedReceipt.finish('error:'+e.message);throw e;}}});"
            +"let ticks=0;function ready(){const b=document.querySelector('.native-share-offer');if(b&&!b.hidden){SharedReceipt.ready();return;}"
            +"if(++ticks<200)setTimeout(ready,25);else SharedReceipt.finish('offer-not-bound');}ready();</script>";
        try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity->{
                preferences.set(activity.getPreferences(Context.MODE_PRIVATE));previous.set(preferences.get().getString("home",null));
                preferences.get().edit().putString("home","https://shared-picker.invalid").commit();
                try {java.lang.reflect.Method open=MainActivity.class.getDeclaredMethod("open",String.class);open.setAccessible(true);open.invoke(activity,"https://shared-picker.invalid");}
                catch(Exception error){throw new AssertionError(error);}
            });
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            while(view.get()==null&&System.nanoTime()<deadline){
                scenario.onActivity(activity->{try{java.lang.reflect.Field f=MainActivity.class.getDeclaredField("web");f.setAccessible(true);view.set((WebView)f.get(activity));}catch(Exception e){throw new AssertionError(e);}});
                if(view.get()==null)Thread.sleep(50);
            }
            assertNotNull("Actual host WebView",view.get());
            scenario.onActivity(activity->{
                WebView web=view.get();web.stopLoading();web.getSettings().setBlockNetworkLoads(true);web.addJavascriptInterface(receipt,"SharedReceipt");
                WebViewClient owner=web.getWebViewClient();
                web.setWebViewClient(new WebViewClient(){
                    @Override public void onPageStarted(WebView page,String url,android.graphics.Bitmap icon){owner.onPageStarted(page,url,icon);}
                    @Override public void onPageFinished(WebView page,String url){owner.onPageFinished(page,url);}
                    @Override public WebResourceResponse shouldInterceptRequest(WebView page,WebResourceRequest request){
                        return new WebResourceResponse("text/html","UTF-8",new java.io.ByteArrayInputStream(html.getBytes(StandardCharsets.UTF_8)));
                    }
                });
                ArrayList<Uri> uris=new ArrayList<>();uris.add(one);uris.add(two);
                // Preserve ActivityScenario's launch action/component so lifecycle
                // ownership is unchanged; parser admission itself is real Intent.
                SharedText offer=SharedText.from(new Intent(Intent.ACTION_SEND_MULTIPLE).setType("application/octet-stream").putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris));
                try {java.lang.reflect.Field f=MainActivity.class.getDeclaredField("incomingShare");f.setAccessible(true);f.set(activity,offer);}
                catch(Exception error){throw new AssertionError(error);}
                web.loadUrl("https://shared-picker.invalid/interaction/");
            });
            assertTrue("Bound shared offer: "+receipt.result,receipt.ready.await(8,TimeUnit.SECONDS));
            scenario.onActivity(activity->{WebView web=view.get();long now=android.os.SystemClock.uptimeMillis();
                MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,web.getWidth()/2f,web.getHeight()/2f,0);
                MotionEvent up=MotionEvent.obtain(now,now+50,MotionEvent.ACTION_UP,web.getWidth()/2f,web.getHeight()/2f,0);
                try{web.dispatchTouchEvent(down);web.dispatchTouchEvent(up);}finally{down.recycle();up.recycle();}
            });
            assertTrue("Actual chooser/content read: "+receipt.result,receipt.done.await(10,TimeUnit.SECONDS));
            JSONArray values=new JSONArray(receipt.result);assertEquals(2,values.length());
            assertArrayEquals(first,android.util.Base64.decode(values.getString(0),android.util.Base64.DEFAULT));
            assertArrayEquals(second,android.util.Base64.decode(values.getString(1),android.util.Base64.DEFAULT));
        } finally {
            context.getContentResolver().delete(one,null,null);context.getContentResolver().delete(two,null,null);
            if(preferences.get()!=null){if(previous.get()==null)preferences.get().edit().remove("home").commit();else preferences.get().edit().putString("home",previous.get()).commit();}
        }
    }
}
