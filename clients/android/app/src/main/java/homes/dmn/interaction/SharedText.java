package homes.dmn.interaction;

import android.content.Intent;
import android.os.Bundle;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;

/** One bounded incoming text offer. It is never a native message or an upload. */
final class SharedText {
    static final int MAX_BYTES = 12000;
    final String id;
    final String text;
    private SharedText(String id, String text) {
        if (!UUID.fromString(id).toString().equals(id) || text == null || text.trim().isEmpty()
                || text.length() > MAX_BYTES || text.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES)
            throw new IllegalArgumentException("Shared text exceeds 12KiB or is empty.");
        this.id = id; this.text = text;
    }
    static SharedText from(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return null;
        // Binary shares are admitted only once the bounded attachment reader is
        // implemented. Never silently keep text while dropping its image/file.
        if (!"text/plain".equals(intent.getType()) || intent.hasExtra(Intent.EXTRA_STREAM)
                || intent.getClipData() != null && intent.getClipData().getItemCount() > 0
                    && intent.getClipData().getItemAt(0).getUri() != null)
            throw new IllegalArgumentException("This build receives shared text and links; attachments are not ready yet.");
        if (intent.getClipData() != null) {
            if (intent.getClipData().getItemCount() > 8) throw new IllegalArgumentException("Too many shared items.");
            for (int n = 0; n < intent.getClipData().getItemCount(); n++)
                if (intent.getClipData().getItemAt(n).getUri() != null)
                    throw new IllegalArgumentException("Shared attachments are not ready in this build.");
        }
        CharSequence value = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
        return new SharedText(UUID.randomUUID().toString(), value == null ? null : value.toString());
    }
    JSONObject json() throws org.json.JSONException {
        return new JSONObject().put("id", id).put("text", text);
    }
    void save(Bundle state) { state.putString("shared_text_id", id); state.putString("shared_text_value", text); }
    static SharedText restore(Bundle state) {
        if (state == null || !state.containsKey("shared_text_id")) return null;
        return new SharedText(state.getString("shared_text_id"), state.getString("shared_text_value"));
    }
}
