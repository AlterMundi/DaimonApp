//! Committed voice preparation. No microphone, native writer or message admission.
use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::{path::Path, process::Stdio, time::Duration};
use tokio::{io::AsyncReadExt, process::Command};

/// Fixed diagnostic vocabulary. Never retain arbitrary subprocess/provider errors.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VoiceFailureStage {
    SourceValidation,
    SourceRead,
    AudioDecode,
    AudioSignal,
    TranscriptionCommand,
    TranscriptValidation,
    TranscriptCommit,
    NativeAdmission,
    ListenerShutdown,
    Unclassified,
}
impl std::fmt::Display for VoiceFailureStage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Voice preparation stage: {:?}", self)
    }
}
impl std::error::Error for VoiceFailureStage {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VoiceFailureDiagnostic {
    pub stage: VoiceFailureStage,
    pub interrupted: bool,
    #[serde(default)]
    pub completed_only: bool,
}
impl VoiceFailureDiagnostic {
    pub fn from_error(error: &anyhow::Error, fallback: VoiceFailureStage) -> Self {
        // anyhow retains typed Context separately from std::error::Error's
        // source chain. Downcast the owned error so that stage is not lost.
        let stage = error
            .downcast_ref::<VoiceFailureStage>()
            .copied()
            .unwrap_or(fallback);
        Self {
            stage,
            interrupted: stage == VoiceFailureStage::ListenerShutdown,
            completed_only: false,
        }
    }
}

pub const MAX_BYTES: usize = 20 * 1024 * 1024;
const MAX_SECONDS: usize = 120;

/// Provider language for a group of retained acoustic originals. This is not
/// an utterance boundary or a transcript assigned to any individual audio clip.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PublicLiveWindow {
    pub dialogue: String,
    pub journal_revision: String,
    pub journal_from: u64,
    pub journal_after: u64,
    pub journal_sha256: String,
    pub text_sha256: String,
    pub input_events: u64,
}

/// Read only the frozen private journal range. Never open a model/provider or
/// interpret the audio again. Output-speaker text cannot become request text.
#[cfg(unix)]
pub fn public_live_window_source(path: &Path, expected: &PublicLiveWindow) -> Result<String> {
    use std::io::{Read, Seek, SeekFrom};
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let digest = |s: &str| {
        s.len() == 64
            && s.bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    };
    if uuid::Uuid::parse_str(&expected.dialogue)
        .ok()
        .is_none_or(|v| v.to_string() != expected.dialogue)
        || path.file_name().and_then(|s| s.to_str())
            != Some(format!("{}.events", expected.dialogue).as_str())
        || !digest(&expected.journal_revision)
        || !digest(&expected.journal_sha256)
        || !digest(&expected.text_sha256)
        || expected.journal_from >= expected.journal_after
        || expected.journal_after - expected.journal_from > 4 * 1024 * 1024
        || !(1..=8192).contains(&expected.input_events)
    {
        bail!("Select one bounded source-bound Live transcript window");
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    let info = file.metadata()?;
    if !info.is_file()
        || info.uid() != unsafe { libc::geteuid() }
        || info.mode() & 0o077 != 0
        || info.len() > 32 * 1024 * 1024
        || expected.journal_after > info.len()
        || format!(
            "{:x}",
            Sha256::digest(
                format!("{}:{}:{}", expected.dialogue, info.dev(), info.ino()).as_bytes()
            )
        ) != expected.journal_revision
    {
        bail!("Live transcript journal ownership or identity changed");
    }
    if expected.journal_from > 0 {
        file.seek(SeekFrom::Start(expected.journal_from - 1))?;
        let mut boundary = [0];
        file.read_exact(&mut boundary)?;
        if boundary != [b'\n'] {
            bail!("Live source window must start at an exact record boundary");
        }
    }
    file.seek(SeekFrom::Start(expected.journal_from))?;
    let mut bytes = vec![0; (expected.journal_after - expected.journal_from) as usize];
    file.read_exact(&mut bytes)?;
    if bytes.last() != Some(&b'\n')
        || format!("{:x}", Sha256::digest(&bytes)) != expected.journal_sha256
    {
        bail!("Live source window changed or remains unconfirmed");
    }
    let mut text = String::new();
    let mut inputs = 0;
    let mut records = 0;
    for line in bytes.split_inclusive(|c| *c == b'\n') {
        records += 1;
        if records > 8192 || line.len() > 32768 {
            bail!("Live source record bound exceeded");
        }
        let row: serde_json::Value = serde_json::from_slice(line)?;
        let event = &row["event"];
        if !row["event_id"].is_string() || row["event_id"] != event["event_id"] {
            bail!("Live source event identity changed");
        }
        if event["type"] != "session.input_transcript.delta" {
            continue;
        }
        let delta = event["delta"]
            .as_str()
            .context("Live input delta missing")?;
        let start = event["start_ms"]
            .as_f64()
            .context("Live input time missing")?;
        let end = event["end_ms"]
            .as_f64()
            .context("Live input time missing")?;
        if delta.is_empty()
            || delta.contains('\0')
            || delta.len() > 12000
            || !start.is_finite()
            || !end.is_finite()
            || start < 0.
            || end < start
            || end > 86400000.
        {
            bail!("Invalid provider input transcript fragment");
        }
        text.push_str(delta);
        inputs += 1;
        if text.len() > 65536 {
            bail!("Complete Live input window exceeds language bound");
        }
    }
    if text.trim().is_empty()
        || inputs != expected.input_events
        || format!("{:x}", Sha256::digest(text.as_bytes())) != expected.text_sha256
    {
        bail!("Live input window does not match its frozen source");
    }
    Ok(text)
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VoiceConfig {
    /// Owner-configured argv, never a shell fragment or model-provided command.
    pub transcription_command: Vec<String>,
    pub transcriber_label: String,
    /// Read an already completed, source-bound transcript. Must never initiate ASR.
    #[serde(default)]
    pub completed_transcription_command: Option<Vec<String>>,
    /// Explicit per-original alternatives; omission keeps the existing route.
    #[serde(default)]
    pub transcription_profiles: BTreeMap<String, TranscriptionProfile>,
    #[serde(default)]
    pub default_transcription_profile: Option<String>,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TranscriptionProfile {
    pub transcription_command: Vec<String>,
    pub transcriber_label: String,
    #[serde(default)]
    pub completed_transcription_command: Option<Vec<String>>,
}
fn default_timeout() -> u64 {
    60
}
impl VoiceConfig {
    pub fn select_profile(&self, profile: Option<&str>) -> Result<Self> {
        let Some(name) = profile else {
            return Ok(self.clone());
        };
        let selected = self
            .transcription_profiles
            .get(name)
            .context("Selected transcription profile is unavailable; no fallback")?;
        let mut config = self.clone();
        config.transcription_command = selected.transcription_command.clone();
        config.transcriber_label = selected.transcriber_label.clone();
        config.completed_transcription_command = selected.completed_transcription_command.clone();
        config.transcription_profiles.clear();
        config.default_transcription_profile = None;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<()> {
        if self
            .default_transcription_profile
            .as_ref()
            .is_some_and(|name| !self.transcription_profiles.contains_key(name))
        {
            bail!("Default transcription profile is unavailable; no fallback");
        }
        if self.transcription_profiles.len() > 4 {
            bail!("Bounded transcription profile selection required");
        }
        for name in self.transcription_profiles.keys() {
            if name.is_empty()
                || name.len() > 32
                || !name
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
            {
                bail!("Invalid transcription profile identity");
            }
            self.select_profile(Some(name))?;
        }
        if self.transcription_command.is_empty()
            || self.transcription_command.len() > 32
            || self
                .transcription_command
                .iter()
                .any(|a| a.is_empty() || a.len() > 4096 || a.contains('\0'))
            || self.transcriber_label.trim().is_empty()
            || self.transcriber_label.len() > 128
            || !(1..=120).contains(&self.timeout_seconds)
        {
            bail!("Invalid bounded voice transcriber configuration");
        }
        if let Some(command) = &self.completed_transcription_command {
            if command.is_empty()
                || command.len() > 32
                || command
                    .iter()
                    .any(|a| a.is_empty() || a.len() > 4096 || a.contains('\0'))
            {
                bail!("Invalid completed-transcript reader command");
            }
        }
        #[cfg(not(unix))]
        bail!("Voice command lifecycle currently requires Unix process groups");
        #[cfg(unix)]
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TranscriptSource {
    pub audio_sha256: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub telegram_file_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capture_id: Option<String>,
    /// Device report retained through canonical relay, not an ASR assertion.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capture_stop: Option<String>,
    pub configured_transcriber: String,
    /// Actual recognizer reported by the source-bound owner helper, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub actual_transcriber: Option<String>,
    pub committed_at: String,
    pub audio_millis: u64,
    pub preparation_millis: u64,
    pub transcription_millis: u64,
    pub interpretation: String,
}

#[cfg(unix)]
struct OwnedCommandGroup(u32);
#[cfg(unix)]
impl Drop for OwnedCommandGroup {
    fn drop(&mut self) {
        unsafe {
            libc::kill(-(self.0 as i32), libc::SIGKILL);
        }
    }
}

/// Own the complete command group until bounded completion, including converters.
/// Stopping preparation affects only this group, never playback or native work.
#[cfg(unix)]
async fn bounded(mut command: Command, limit: usize, timeout: u64) -> Result<Vec<u8>> {
    use std::os::unix::process::CommandExt;
    command.as_std_mut().process_group(0);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    let mut child = command.spawn().context("Voice command unavailable")?;
    let id = child.id().context("Missing owned voice process")?;
    let group = OwnedCommandGroup(id);
    let mut stdout = child
        .stdout
        .take()
        .context("Missing voice output")?
        .take(limit as u64 + 1);
    let mut output = vec![];
    let result = tokio::time::timeout(Duration::from_secs(timeout), async {
        stdout.read_to_end(&mut output).await?;
        if output.len() > limit {
            bail!("Voice command output exceeded bound");
        }
        if !child.wait().await?.success() {
            bail!("Voice command did not complete successfully");
        }
        Ok(())
    })
    .await;
    // Also collect descendants left by a failed, timed-out or early-exiting adapter.
    drop(group);
    let _ = child.wait().await;
    result.context("Voice preparation expired; no automatic retry")??;
    Ok(output)
}
#[cfg(not(unix))]
async fn bounded(_command: Command, _limit: usize, _timeout: u64) -> Result<Vec<u8>> {
    bail!("Voice unavailable on this platform")
}

pub async fn transcribe(
    config: &VoiceConfig,
    path: &Path,
    file_id: &str,
) -> Result<(String, TranscriptSource)> {
    let selected = config.select_profile(config.default_transcription_profile.as_deref())?;
    transcribe_committed(&selected, path, Some(file_id), None, None).await
}

pub async fn transcribe_committed(
    config: &VoiceConfig,
    path: &Path,
    telegram_file_id: Option<&str>,
    capture_id: Option<&str>,
    expected_sha256: Option<&str>,
) -> Result<(String, TranscriptSource)> {
    if telegram_file_id.is_some() == capture_id.is_some() {
        bail!(VoiceFailureStage::SourceValidation);
    }
    let preparation_started = std::time::Instant::now();
    let bytes = read_media(path)
        .await
        .context(VoiceFailureStage::SourceRead)?;
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        bail!(VoiceFailureStage::SourceValidation);
    }
    let hash = format!("{:x}", Sha256::digest(&bytes));
    if expected_sha256.is_some_and(|expected| expected != hash) {
        bail!(VoiceFailureStage::SourceValidation);
    }
    // Decode the whole bounded clip before paid ASR. Digital silence is not speech.
    let mut decode = Command::new("ffmpeg");
    decode
        .args(["-v", "error", "-nostdin", "-i"])
        .arg(path)
        .args(["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]);
    let pcm = bounded(decode, MAX_SECONDS * 16000 * 4, 15)
        .await
        .context(VoiceFailureStage::AudioDecode)?;
    if pcm.is_empty() || pcm.len() % 4 != 0 {
        bail!(VoiceFailureStage::AudioDecode);
    }
    let peak = pcm
        .chunks_exact(4)
        .map(|v| f32::from_le_bytes(v.try_into().expect("sample width")).abs())
        .fold(0f32, f32::max);
    if !peak.is_finite() || peak < 0.0001 {
        bail!(VoiceFailureStage::AudioSignal);
    }
    let mut command = Command::new(&config.transcription_command[0]);
    command.args(&config.transcription_command[1..]).arg(path);
    let transcription_started = std::time::Instant::now();
    let output = bounded(command, 64 * 1024, config.timeout_seconds)
        .await
        .context(VoiceFailureStage::TranscriptionCommand)?;
    let transcription_millis = transcription_started.elapsed().as_millis() as u64;
    let value: serde_json::Value =
        serde_json::from_slice(&output).context(VoiceFailureStage::TranscriptValidation)?;
    if value["final"] == false || value["partial"] == true {
        bail!(VoiceFailureStage::TranscriptValidation);
    }
    let actual_transcriber = match value.get("streaming_model") {
        None => None,
        Some(model) => match model.as_str() {
            Some(
                "gemini-3.8-live" | "gemini-3.5-transcribe-live" | "qwen-audio-3.0-realtime-plus",
            ) => model.as_str().map(str::to_owned),
            _ => bail!(VoiceFailureStage::TranscriptValidation),
        },
    };
    let text = value["text"]
        .as_str()
        .context(VoiceFailureStage::TranscriptValidation)?
        .trim()
        .to_string();
    if text.is_empty() || text.len() > 16000 {
        bail!(VoiceFailureStage::TranscriptValidation);
    }
    if format!(
        "{:x}",
        Sha256::digest(
            read_media(path)
                .await
                .context(VoiceFailureStage::SourceRead)?
        )
    ) != hash
    {
        bail!(VoiceFailureStage::SourceValidation);
    }
    Ok((text,TranscriptSource{audio_sha256:hash,telegram_file_id:telegram_file_id.map(str::to_owned),capture_id:capture_id.map(str::to_owned),capture_stop:None,configured_transcriber:config.transcriber_label.clone(),actual_transcriber,committed_at:chrono::Utc::now().to_rfc3339(),audio_millis:(pcm.len()/4) as u64*1000/16000,preparation_millis:preparation_started.elapsed().as_millis() as u64,transcription_millis,interpretation:"Machine transcription of the original human voice clip; not exact verified written speech".into()}))
}

/// Verify the exact private canonical WAV before importing an owner-attested
/// OpenAI result. This reads no provider configuration and never runs ASR.
#[cfg(unix)]
pub fn public_interpretation_source(
    path: &Path,
    id: &str,
    expected_sha256: &str,
    audio_millis: u64,
    transcription_millis: u64,
) -> Result<TranscriptSource> {
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let started = std::time::Instant::now();
    let parent = std::fs::symlink_metadata(path.parent().context("Missing original directory")?)?;
    if !parent.is_dir() || parent.uid() != unsafe { libc::geteuid() } || parent.mode() & 0o077 != 0
    {
        bail!("Public interpretation requires the private owner original directory");
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    let info = file.metadata()?;
    const MAX_WAV: u64 = 120 * 32000 + 44;
    if !info.is_file()
        || info.uid() != unsafe { libc::geteuid() }
        || info.mode() & 0o077 != 0
        || info.len() <= 44
        || info.len() > MAX_WAV
        || transcription_millis > 120000
    {
        bail!("Public interpretation requires a bounded private WAV");
    }
    let mut bytes = Vec::new();
    file.take(MAX_WAV + 1).read_to_end(&mut bytes)?;
    if bytes.len() <= 44
        || bytes.len() as u64 > MAX_WAV
        || (bytes.len() - 44) % 2 != 0
        || format!("{:x}", Sha256::digest(&bytes)) != expected_sha256
        || &bytes[0..4] != b"RIFF"
        || &bytes[8..20] != b"WAVEfmt \x10\0\0\0"
        || &bytes[20..36] != b"\x01\0\x01\0\x80\x3e\0\0\0\x7d\0\0\x02\0\x10\0"
        || &bytes[36..40] != b"data"
        || u32::from_le_bytes(bytes[4..8].try_into()?) as usize != bytes.len() - 8
        || u32::from_le_bytes(bytes[40..44].try_into()?) as usize != bytes.len() - 44
        || audio_millis == 0
        || audio_millis != (bytes.len() as u64 - 44) * 1000 / 32000
    {
        bail!("Completed public interpretation does not match its exact PCM original");
    }
    Ok(TranscriptSource {
        audio_sha256: expected_sha256.into(), telegram_file_id: None, capture_id: Some(id.into()),
        capture_stop: None, configured_transcriber: "OpenAI public API file transcription".into(),
        actual_transcriber: Some("gpt-transcribe".into()), committed_at: chrono::Utc::now().to_rfc3339(),
        audio_millis, preparation_millis: started.elapsed().as_millis() as u64, transcription_millis,
        interpretation: "Machine transcription of the original human voice clip; not exact verified written speech".into(),
    })
}

async fn read_media(path: &Path) -> Result<Vec<u8>> {
    let mut file = tokio::fs::File::open(path)
        .await?
        .take(MAX_BYTES as u64 + 1);
    let mut bytes = vec![];
    file.read_to_end(&mut bytes).await?;
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        bail!("Voice media size outside bounds");
    }
    Ok(bytes)
}

/// Remove only the exact owned download whose interpretation was durably committed.
/// The caller must commit text/provenance first. Cleanup failure never retries ASR.
#[cfg(unix)]
pub fn retire_transcribed_clip(path: &Path, expected_sha256: &str) -> Result<()> {
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let mut file = match std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    let info = file.metadata()?;
    if !info.is_file()
        || info.uid() != unsafe { libc::geteuid() }
        || info.mode() & 0o077 != 0
        || info.len() > MAX_BYTES as u64
    {
        bail!("Committed voice cleanup requires a bounded private owner file");
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_BYTES || format!("{:x}", Sha256::digest(&bytes)) != expected_sha256 {
        bail!("Committed voice bytes changed before cleanup");
    }
    let current = std::fs::symlink_metadata(path)?;
    if current.dev() != info.dev() || current.ino() != info.ino() {
        bail!("Committed voice path changed before cleanup");
    }
    std::fs::remove_file(path)?;
    std::fs::File::open(path.parent().context("Voice cleanup parent unavailable")?)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
pub fn retire_transcribed_clip(_path: &Path, _expected_sha256: &str) -> Result<()> {
    bail!("Committed voice cleanup requires Unix file ownership");
}

#[cfg(all(test, unix))]
mod retirement_tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt, symlink};
    #[test]
    fn committed_payload_disposal_is_exact_and_idempotent() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("voice.ogg");
        std::fs::write(&path, b"owned confirmed clip").unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let hash = format!("{:x}", Sha256::digest(b"owned confirmed clip"));
        assert!(retire_transcribed_clip(&path, &"0".repeat(64)).is_err());
        assert!(path.exists());
        retire_transcribed_clip(&path, &hash).unwrap();
        assert!(!path.exists());
        retire_transcribed_clip(&path, &hash).unwrap();
    }
    #[test]
    fn public_or_linked_sources_are_preserved() {
        let root = tempfile::tempdir().unwrap();
        let source = root.path().join("source");
        let link = root.path().join("link");
        std::fs::write(&source, b"private original").unwrap();
        let hash = format!("{:x}", Sha256::digest(b"private original"));
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(retire_transcribed_clip(&source, &hash).is_err());
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o600)).unwrap();
        symlink(&source, &link).unwrap();
        assert!(retire_transcribed_clip(&link, &hash).is_err());
        assert!(source.exists());
    }
}

/// Serialize bounded Telegram media publication; no transcription or work lock.
pub struct DownloadReservation {
    pub directory: std::path::PathBuf,
    _lock: std::fs::File,
}

#[cfg(unix)]
pub fn reserve_telegram_download(database: &Path) -> Result<DownloadReservation> {
    use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
    let database = std::path::absolute(database)?;
    let directory = std::path::PathBuf::from(format!("{}.telegram-voice", database.display()));
    match std::fs::DirBuilder::new().mode(0o700).create(&directory) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    let info = std::fs::symlink_metadata(&directory)?;
    if !info.is_dir() || info.uid() != unsafe { libc::geteuid() } || info.mode() & 0o077 != 0 {
        bail!("Voice download storage must be a private owner directory");
    }
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(directory.join("admission.lock"))?;
    let info = lock.metadata()?;
    if !info.is_file() || info.uid() != unsafe { libc::geteuid() } || info.mode() & 0o077 != 0 {
        bail!("Voice download admission lock changed");
    }
    use std::os::fd::AsRawFd;
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
            break;
        }
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::WouldBlock || std::time::Instant::now() >= deadline {
            bail!("Voice download storage busy; text remains available");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let mut bytes = 0u64;
    let mut count = 0usize;
    for entry in std::fs::read_dir(&directory)? {
        let entry = entry?;
        let info = match std::fs::symlink_metadata(entry.path()) {
            Ok(info) => info,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error.into()),
        };
        if !info.is_file() || info.uid() != unsafe { libc::geteuid() } || info.mode() & 0o077 != 0 {
            bail!("Voice download storage changed");
        }
        bytes = bytes
            .checked_add(info.len())
            .context("Voice storage size overflow")?;
        if entry.file_name() != "admission.lock" {
            count += 1;
        }
        if count >= 128 || bytes > 256 * 1024 * 1024 - MAX_BYTES as u64 {
            bail!("Voice download storage full; text remains available");
        }
    }
    std::fs::File::open(&directory)?.sync_all()?;
    std::fs::File::open(directory.parent().context("Voice storage parent missing")?)?.sync_all()?;
    Ok(DownloadReservation {
        directory,
        _lock: lock,
    })
}

#[cfg(all(test, unix))]
mod capacity_tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt, symlink};
    #[test]
    fn download_admission_reserves_maximum_and_releases_only_the_lock() {
        let root = tempfile::tempdir().unwrap();
        let db = root.path().join("state.sqlite");
        let reservation = reserve_telegram_download(&db).unwrap();
        assert!(reserve_telegram_download(&db).is_err());
        let protected = reservation.directory.join("unconfirmed");
        let file = std::fs::File::create(&protected).unwrap();
        std::fs::set_permissions(&protected, std::fs::Permissions::from_mode(0o600)).unwrap();
        file.set_len(256 * 1024 * 1024).unwrap();
        drop(file);
        drop(reservation);
        assert!(reserve_telegram_download(&db).is_err());
        assert!(protected.exists());
        std::fs::remove_file(&protected).unwrap();
        assert!(reserve_telegram_download(&db).is_ok());
    }
    #[test]
    fn relative_database_paths_keep_the_existing_working_directory_resolution() {
        let root = tempfile::tempdir_in(".").unwrap();
        let relative = root
            .path()
            .strip_prefix(std::env::current_dir().unwrap())
            .unwrap_or(root.path());
        assert!(!relative.is_absolute());
        let reservation = reserve_telegram_download(&relative.join("state.sqlite")).unwrap();
        assert!(reservation.directory.is_absolute());
        assert_eq!(
            reservation
                .directory
                .parent()
                .unwrap()
                .canonicalize()
                .unwrap(),
            root.path().canonicalize().unwrap()
        );
    }
    #[test]
    fn tiny_pending_files_and_links_are_preserved_and_refuse_admission() {
        let root = tempfile::tempdir().unwrap();
        let db = root.path().join("state.sqlite");
        let reservation = reserve_telegram_download(&db).unwrap();
        let directory = reservation.directory.clone();
        drop(reservation);
        for index in 0..128 {
            let p = directory.join(index.to_string());
            std::fs::write(&p, b"x").unwrap();
            std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
        assert!(reserve_telegram_download(&db).is_err());
        assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 129);
        for index in 0..128 {
            std::fs::remove_file(directory.join(index.to_string())).unwrap();
        }
        let original = root.path().join("unrelated");
        std::fs::write(&original, b"preserve").unwrap();
        symlink(&original, directory.join("linked")).unwrap();
        assert!(reserve_telegram_download(&db).is_err());
        assert_eq!(std::fs::read(original).unwrap(), b"preserve");
    }
}

#[cfg(not(unix))]
pub fn reserve_telegram_download(_database: &Path) -> Result<DownloadReservation> {
    bail!("Voice download storage currently requires Unix ownership and locking");
}

#[cfg(all(test, unix))]
mod public_interpretation_tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn public_interpretation_requires_exact_private_canonical_wave() {
        let root = tempfile::tempdir().unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let path = root.path().join("capture");
        let mut data = Vec::new();
        data.extend(b"RIFF");
        data.extend(6436u32.to_le_bytes());
        data.extend(b"WAVEfmt \x10\0\0\0\x01\0\x01\0\x80\x3e\0\0\0\x7d\0\0\x02\0\x10\0data");
        data.extend(6400u32.to_le_bytes());
        data.resize(6444, 0);
        std::fs::write(&path, &data).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let hash = format!("{:x}", Sha256::digest(&data));
        let proof = public_interpretation_source(&path, "capture", &hash, 200, 30).unwrap();
        assert_eq!(proof.actual_transcriber.as_deref(), Some("gpt-transcribe"));
        assert_eq!(proof.audio_millis, 200);
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
        assert!(public_interpretation_source(&path, "capture", &hash, 200, 30).is_err());
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        assert!(public_interpretation_source(&path, "capture", &hash, 201, 30).is_err());
        assert!(public_interpretation_source(&path, "capture", &"b".repeat(64), 200, 30).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(public_interpretation_source(&path, "capture", &hash, 200, 30).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let link = root.path().join("link");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(public_interpretation_source(&link, "capture", &hash, 200, 30).is_err());
        data[24] = 0;
        std::fs::write(&path, &data).unwrap();
        let changed = format!("{:x}", Sha256::digest(&data));
        assert!(public_interpretation_source(&path, "capture", &changed, 200, 30).is_err());
    }
    #[test]
    fn explicit_transcription_profile_preserves_default_and_refuses_fallback() {
        let mut config: VoiceConfig = serde_json::from_value(serde_json::json!({
            "transcription_command":["legacy"],"transcriber_label":"existing",
            "transcription_profiles":{"openai":{
                "transcription_command":["openai-final"],"transcriber_label":"OpenAI gpt-transcribe",
                "completed_transcription_command":["openai-read-only"]}}
        })).unwrap();
        config.validate().unwrap();
        assert_eq!(
            config.select_profile(None).unwrap().transcription_command,
            ["legacy"]
        );
        let selected = config.select_profile(Some("openai")).unwrap();
        assert_eq!(selected.transcription_command, ["openai-final"]);
        assert_eq!(
            selected.completed_transcription_command.unwrap(),
            ["openai-read-only"]
        );
        assert!(config.select_profile(Some("missing")).is_err());
        assert_eq!(config.transcription_command, ["legacy"]);
        config.default_transcription_profile = Some("openai".into());
        config.validate().unwrap();
        assert_eq!(
            config
                .select_profile(config.default_transcription_profile.as_deref())
                .unwrap()
                .transcription_command,
            ["openai-final"]
        );
        config.default_transcription_profile = Some("missing".into());
        assert!(config.validate().is_err());
    }
}

#[cfg(all(test, unix))]
mod live_window_tests {
    use super::*;
    use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};

    #[test]
    fn live_window_reads_only_input_and_keeps_the_frozen_prefix() {
        let root = tempfile::tempdir().unwrap();
        let dialogue = uuid::Uuid::now_v7().to_string();
        let path = root.path().join(format!("{dialogue}.events"));
        let rows = [
            ("in1", "session.input_transcript.delta", "Dale, "),
            (
                "out",
                "session.output_transcript.delta",
                "Do not turn this into human speech",
            ),
            ("in2", "session.input_transcript.delta", "CompAII."),
        ];
        let bytes=rows.iter().map(|(id,kind,text)|serde_json::to_string(&serde_json::json!({"event_id":id,"sha256":"a".repeat(64),"event":{"event_id":id,"type":kind,"delta":text,"start_ms":0,"end_ms":12}})).unwrap()+"\n").collect::<String>().into_bytes();
        std::fs::write(&path, &bytes).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let info = path.metadata().unwrap();
        let text = "Dale, CompAII.";
        let proof = PublicLiveWindow {
            dialogue: dialogue.clone(),
            journal_revision: format!(
                "{:x}",
                Sha256::digest(format!("{dialogue}:{}:{}", info.dev(), info.ino()))
            ),
            journal_from: 0,
            journal_after: bytes.len() as u64,
            journal_sha256: format!("{:x}", Sha256::digest(&bytes)),
            text_sha256: format!("{:x}", Sha256::digest(text)),
            input_events: 2,
        };
        assert_eq!(public_live_window_source(&path, &proof).unwrap(), text);
        use std::io::Write;
        std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(b"late fragment not in this prefix\n")
            .unwrap();
        assert_eq!(public_live_window_source(&path, &proof).unwrap(), text);
        let mut bad = proof.clone();
        bad.text_sha256 = "b".repeat(64);
        assert!(public_live_window_source(&path, &bad).is_err());
        bad = proof.clone();
        bad.journal_from = 1;
        assert!(public_live_window_source(&path, &bad).is_err());
        bad = proof.clone();
        bad.input_events = 3;
        assert!(public_live_window_source(&path, &bad).is_err());
        let link = root.path().join("link");
        symlink(&path, &link).unwrap();
        assert!(public_live_window_source(&link, &proof).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(public_live_window_source(&path, &proof).is_err());
    }
}

#[cfg(test)]
mod failure_diagnostic_tests {
    use super::*;
    #[test]
    fn fixed_stage_never_serializes_underlying_error_text() {
        let private = "private transcript/provider stderr/token";
        let error = anyhow::anyhow!(private).context(VoiceFailureStage::TranscriptionCommand);
        let diagnostic =
            VoiceFailureDiagnostic::from_error(&error, VoiceFailureStage::Unclassified);
        assert_eq!(
            serde_json::to_value(&diagnostic).unwrap(),
            serde_json::json!({"stage":"transcription_command","interrupted":false,"completed_only":false})
        );
        assert!(
            !serde_json::to_string(&diagnostic)
                .unwrap()
                .contains(private)
        );
        let interrupted = VoiceFailureDiagnostic::from_error(
            &anyhow::anyhow!(VoiceFailureStage::ListenerShutdown),
            VoiceFailureStage::Unclassified,
        );
        assert!(interrupted.interrupted);
    }
    #[tokio::test]
    async fn missing_source_fails_before_any_transcriber_command() {
        let root = tempfile::tempdir().unwrap();
        let config:VoiceConfig=serde_json::from_value(serde_json::json!({"transcription_command":["/not-an-executable"],"transcriber_label":"Synthetic fixture"})).unwrap();
        let error = transcribe_committed(
            &config,
            &root.path().join("missing"),
            None,
            Some("capture"),
            None,
        )
        .await
        .unwrap_err();
        assert_eq!(
            VoiceFailureDiagnostic::from_error(&error, VoiceFailureStage::Unclassified).stage,
            VoiceFailureStage::SourceRead
        );
        assert_eq!(root.path().read_dir().unwrap().count(), 0);
    }
}
