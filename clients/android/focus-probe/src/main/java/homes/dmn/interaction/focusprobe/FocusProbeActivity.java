package homes.dmn.interaction.focusprobe;

import android.app.Activity;
import android.app.Service;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Process;

/** Separate test UID, no network/microphone/storage. Always ends within 30 seconds. */
public final class FocusProbeActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        startForegroundService(new Intent(this, Player.class));
        finish();
    }
    public static final class Player extends Service {
        private static final String CONTROL = "homes.dmn.interaction.focusprobe.CONTROL";
        private final Handler handler = new Handler(Looper.getMainLooper());
        private AudioManager manager;
        private AudioFocusRequest focus;
        private AudioTrack track;
        private boolean paused;
        private int losses, gains, pausedHead;
        private final Runnable tick = new Runnable() {
            @Override public void run() { if (track != null) { emit("position", 0); handler.postDelayed(this, 50); } }
        };
        @Override public void onCreate() {
            super.onCreate();
            getSystemService(NotificationManager.class).createNotificationChannel(
                new NotificationChannel("focus-test", "Bounded focus test", NotificationManager.IMPORTANCE_LOW));
            startForeground(1, new Notification.Builder(this, "focus-test")
                .setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("Bounded test focus probe").build());
            handler.postDelayed(this::stopSelf, 30000);
            try {
                manager = getSystemService(AudioManager.class);
                AudioAttributes attributes = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
                focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes)
                    .setWillPauseWhenDucked(true).setOnAudioFocusChangeListener(this::changed, handler).build();
                if (manager.requestAudioFocus(focus) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED)
                    throw new IllegalStateException("Probe focus was not granted");
                byte[] tone = new byte[48000];
                for (int n = 0; n < 24000; n++) {
                    short sample = (short)(Math.sin(2 * Math.PI * 220 * n / 24000) * 1024);
                    tone[n * 2] = (byte)sample; tone[n * 2 + 1] = (byte)(sample >> 8);
                }
                track = new AudioTrack.Builder().setAudioAttributes(attributes)
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(24000).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                    .setBufferSizeInBytes(tone.length).setTransferMode(AudioTrack.MODE_STATIC).build();
                if (track.getState() != AudioTrack.STATE_INITIALIZED || track.write(tone, 0, tone.length) != tone.length
                        || track.setLoopPoints(0, 24000, -1) != AudioTrack.SUCCESS)
                    throw new IllegalStateException("Probe track unavailable");
                track.play(); emit("ready", 0); handler.post(tick);
            } catch (Exception error) { android.util.Log.e("DaimonFocusProbe", "Probe initialization failed", error); emit("error", 0); stopSelf(); }
        }
        private void changed(int change) {
            if (track == null) return;
            if (change == AudioManager.AUDIOFOCUS_LOSS || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT
                    || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
                track.pause(); paused = true; pausedHead = track.getPlaybackHeadPosition(); losses++; emit("paused", change);
            } else if (change == AudioManager.AUDIOFOCUS_GAIN && paused) {
                track.play(); paused = false; gains++; emit("resumed", change);
            }
        }
        private void emit(String phase, int change) {
            sendBroadcast(new Intent("homes.dmn.interaction.focusprobe.STATE").setPackage("homes.dmn.interaction.pilot")
                .putExtra("phase", phase).putExtra("uid", Process.myUid()).putExtra("change", change)
                .putExtra("losses", losses).putExtra("gains", gains).putExtra("paused_head", pausedHead)
                .putExtra("head", track == null ? 0 : track.getPlaybackHeadPosition()), CONTROL);
        }
        @Override public int onStartCommand(Intent intent, int flags, int id) { return START_NOT_STICKY; }
        @Override public IBinder onBind(Intent intent) { return null; }
        @Override public void onDestroy() {
            handler.removeCallbacksAndMessages(null);
            if (track != null) { try { track.stop(); } catch (IllegalStateException ignored) { } track.release(); track = null; }
            if (focus != null && manager != null) manager.abandonAudioFocusRequest(focus);
            stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy();
        }
    }
}
