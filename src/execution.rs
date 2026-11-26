//! Gateway references are scoped by logical conversation and receiving harness.
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Harness {
    Codex,
    Claude,
    Antigravity,
    Goose,
}

impl Harness {
    pub(crate) const fn name(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
            Self::Antigravity => "antigravity",
            Self::Goose => "goose",
        }
    }
}

#[derive(Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ExecutionBinding {
    pub conversation_id: i64,
    pub revision: String,
    pub harness: Harness,
    pub native_session: Option<String>,
}

impl ExecutionBinding {
    pub(crate) fn matches(&self, harness: Harness, native_session: &str) -> bool {
        self.harness == harness && self.native_session.as_deref() == Some(native_session)
    }
}
