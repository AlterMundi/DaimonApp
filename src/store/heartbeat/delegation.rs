//! Causal attention ownership travels with the existing immutable workflow.
//! Each fresh worker reserves from the original account, never a copied balance.
use super::*;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(in crate::store) struct AttentionOwner {
    pub entry: SessionKey,
    pub native: String,
    pub generation: u64,
    #[serde(default)]
    pub activation: Option<lanes::Activation>,
}

pub(in crate::store) fn owner_current_on(
    conn: &Connection,
    human: i64,
    owner: &AttentionOwner,
) -> Result<()> {
    let activation = owner
        .activation
        .as_ref()
        .context("Attention lane attribution missing")?;
    anyhow::ensure!(
        lanes::current_on(conn, human, owner.entry, activation)?,
        "Attention lane is paused or stale"
    );
    let (_, native) = super::super::presentation::entry_on(conn, human, owner.entry)?;
    anyhow::ensure!(
        native == owner.native
            && generation_current_on(conn, human, owner.entry, owner.generation)?,
        "Attention owner is paused, stale or rebound"
    );
    Ok(())
}

pub(in crate::store) fn owner_for_turn_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    native: &str,
    physical: &str,
) -> Result<Option<AttentionOwner>> {
    let (session, bound) = super::super::presentation::entry_on(conn, human, entry)?;
    anyhow::ensure!(bound == native, "Attention caller binding changed");
    let mut q = conn.prepare("SELECT b.value FROM bot_state b JOIN turns t ON b.key='heartbeat_execution:'||t.id WHERE t.session_id=?1 AND t.from_user_id=?2 AND json_extract(b.value,'$.native')=?3 AND json_extract(b.value,'$.physical')=?4 LIMIT 2")?;
    let rows = q
        .query_map(params![session, human, native, physical], |r| {
            r.get::<_, String>(0)
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if rows.is_empty() {
        return Ok(None);
    }
    anyhow::ensure!(rows.len() == 1, "Ambiguous attention execution");
    let record: Value = serde_json::from_str(&rows[0])?;
    anyhow::ensure!(
        record["phase"] == "owned",
        "Attention execution no longer owns delegated admission"
    );
    let owner = match record.get("owner") {
        Some(value) => serde_json::from_value(value.clone())?,
        None => AttentionOwner {
            activation: Some(serde_json::from_value(record["activation"].clone())?),
            entry,
            native: native.into(),
            generation: record["generation"]
                .as_u64()
                .context("Missing attention generation")?,
        },
    };
    owner_current_on(conn, human, &owner)?;
    Ok(Some(owner))
}

#[allow(clippy::too_many_arguments)]
pub(in crate::store) fn claim_delegate_on(
    tx: &rusqlite::Transaction<'_>,
    local: i64,
    human: i64,
    target: SessionKey,
    native: &str,
    owner: &AttentionOwner,
    instruction: &str,
) -> Result<()> {
    owner_current_on(tx, human, owner)?;
    anyhow::ensure!(
        super::executions::load(tx, local)?.is_none(),
        "Delegated execution already claimed; no new allocation"
    );
    let fresh:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id JOIN interaction_instructions i ON i.session_id=s.id WHERE t.id=?1 AND t.from_user_id=?2 AND t.status='running' AND s.creator_user_id=?2 AND s.chat_id=?3 AND s.thread_id=?4 AND s.codex_thread_id=?5 AND i.id=?6 AND i.phase='submitting' AND json_extract(i.doc,'$.local_turn')=t.id AND NOT EXISTS(SELECT 1 FROM native_collections n WHERE n.local_turn=t.id AND n.first_turn<>'') AND NOT EXISTS(SELECT 1 FROM interaction_instructions other WHERE json_extract(other.doc,'$.local_turn')=t.id AND other.id<>i.id) AND NOT EXISTS(SELECT 1 FROM conversation_inputs c WHERE c.local_turn=t.id) AND NOT EXISTS(SELECT 1 FROM incoming_updates u WHERE u.turn_id=t.id))",params![local,human,target.chat_id,target.thread_id,native,instruction],|r|r.get(0))?;
    anyhow::ensure!(
        fresh,
        "Delegation requires its own exclusive fresh execution"
    );
    let retained = super::executions::selected(tx, human, owner.entry)?;
    let active = retained
        .iter()
        .filter(|r| matches!(r["phase"].as_str(), Some("owned" | "stopping")))
        .count();
    anyhow::ensure!(active < 16, "Attention execution capacity reached");
    let (account, _) = super::super::presentation::entry_on(tx, human, owner.entry)?;
    let allocation = super::resources::reserve_on(tx, account, human)?;
    for old in retained
        .iter()
        .filter(|r| matches!(r["phase"].as_str(), Some("terminal" | "transferred")))
        .skip(15 - active)
    {
        tx.execute(
            "DELETE FROM bot_state WHERE key='heartbeat_execution:'||?1",
            [old["local"].as_i64().context("Invalid retained local")?],
        )?;
    }
    super::executions::save(
        tx,
        local,
        &json!({"local":local,"generation":owner.generation,"activation":owner.activation,"source":instruction,"native":native,"physical":null,"phase":"owned","terminal_status":null,"owner":owner,"inference_allowance":allocation}),
    )?;
    Ok(())
}
