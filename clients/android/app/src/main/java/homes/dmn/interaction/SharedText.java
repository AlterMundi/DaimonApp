package homes.dmn.interaction;

import android.content.Intent;
import android.os.Bundle;
import android.net.Uri;
import java.util.ArrayList;
import java.util.List;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;

/** One bounded offer; URI grants remain Android-owned until explicit picker use.
 * No native byte copies, network, persistable grants, background service or upload.
 * Existing WebView FileInput enforces eight files/20MiB each/40MiB total before Send.
 */
final class SharedText {
    static final int MAX_BYTES = 12000;
    final String id;
    final String text;
    final ArrayList<Uri> files;
    static final String PICKER = "application/x-daimon-share-";
    private SharedText(String id, String text, List<Uri> files) {
        if (!UUID.fromString(id).toString().equals(id) || text == null || text.trim().isEmpty() && files.isEmpty()
                || text.length() > MAX_BYTES || text.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES)
            throw new IllegalArgumentException("Shared text exceeds 12KiB or is empty.");
        if (files.size() > 8) throw new IllegalArgumentException("Share at most eight files.");
        this.files = new ArrayList<>();
        for (Uri uri : files) {
            if (uri == null || !"content".equals(uri.getScheme()) || this.files.contains(uri))
                throw new IllegalArgumentException("Share distinct content files using Android's read grant.");
            this.files.add(uri);
        }
        this.id = id; this.text = text;
    }
    static SharedText from(Intent intent) {
        if (intent == null || !(Intent.ACTION_SEND.equals(intent.getAction())
                || Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction()))) return null;
        ArrayList<Uri> files = new ArrayList<>();
        if (Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction())) {
            ArrayList<Uri> streams = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (streams != null) files.addAll(streams);
        } else {
            Uri stream = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (stream != null) files.add(stream);
        }
        ArrayList<Uri> clips = new ArrayList<>();
        if (intent.getClipData() != null) {
            if (intent.getClipData().getItemCount() > 9) throw new IllegalArgumentException("Too many shared items.");
            for (int n=0;n<intent.getClipData().getItemCount();n++) {
                Uri uri=intent.getClipData().getItemAt(n).getUri();
                if (uri != null) clips.add(uri);
            }
        }
        if (files.isEmpty()) files.addAll(clips);
        else if (!clips.isEmpty() && !files.equals(clips))
            throw new IllegalArgumentException("Shared file descriptions differ. Review the source selection.");
        if (files.isEmpty() && !"text/plain".equals(intent.getType()))
            throw new IllegalArgumentException("Shared attachment bytes are unavailable. Nothing was added.");
        CharSequence value = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
        return new SharedText(UUID.randomUUID().toString(), value == null ? "" : value.toString(), files);
    }

    JSONObject json() throws org.json.JSONException {
        return new JSONObject().put("id", id).put("text", text).put("fileCount", files.size());
    }
    void save(Bundle state) { state.putString("shared_text_id", id); state.putString("shared_text_value", text); state.putParcelableArrayList("shared_files", files); }
    static SharedText restore(Bundle state) {
        if (state == null || !state.containsKey("shared_text_id")) return null;
        ArrayList<Uri> files=state.getParcelableArrayList("shared_files");
        return new SharedText(state.getString("shared_text_id"), state.getString("shared_text_value"), files == null ? java.util.Collections.emptyList() : files);
    }
}
