//! Semantic view of one verified, immutable Holodeck observation.
use serde_json::{Map, Value, json};

fn select(value: &Value, keys: &[&str]) -> Value {
    Value::Object(
        keys.iter()
            .filter_map(|key| value.get(key).map(|value| ((*key).into(), value.clone())))
            .collect(),
    )
}

pub(super) fn same_lane(previous: &Value, current: &Value) -> bool {
    ["observer", "run", "edition", "scope"]
        .into_iter()
        .all(|key| {
            current[key].as_str().is_some_and(|value| !value.is_empty())
                && previous[key] == current[key]
        })
        && (current["scope"] != "structured-interior-room"
            || (current["place"]["id"]
                .as_str()
                .is_some_and(|value| !value.is_empty())
                && previous["place"]["id"] == current["place"]["id"]))
}

pub(super) fn project(
    observation: &Value,
    previous: Option<&Map<String, Value>>,
) -> Map<String, Value> {
    let prior_pose = previous.and_then(|state| state.get("pose"));
    let prior_cell = prior_pose.and_then(|pose| pose["cell"].as_array());
    let position = &observation["clientReportedView"]["value"]["local"]["position"];
    let cell: Option<Vec<i64>> = ["x", "y", "z"]
        .iter()
        .enumerate()
        .map(|(index, axis)| {
            let coordinate = position[*axis].as_f64()?;
            if coordinate.abs() > 1e9 {
                return None;
            }
            let cell = coordinate * 2.0;
            let old = prior_cell
                .and_then(|values| values.get(index))
                .and_then(Value::as_i64);
            Some(
                old.filter(|old| cell >= *old as f64 - 0.15 && cell < *old as f64 + 1.15)
                    .unwrap_or_else(|| cell.floor() as i64),
            )
        })
        .collect();
    let mut nodes = observation["nodes"].clone();
    if let Some(nodes) = nodes.as_object_mut() {
        for node in nodes.values_mut() {
            if let Some(progress) = node.get_mut("progress").and_then(Value::as_object_mut) {
                progress.remove("through");
            }
        }
    }
    let activity = observation["place"]
        .get("activity")
        .filter(|v| !v.is_null())
        .unwrap_or(&observation["activity"]);
    let focus = observation["focus"].as_array().map(|signals| {
        signals
            .iter()
            .map(|signal| {
                select(
                    signal,
                    &[
                        "actor",
                        "kind",
                        "name",
                        "target",
                        "revision",
                        "currentRevision",
                        "status",
                    ],
                )
            })
            .collect::<Vec<_>>()
    });
    let mut events = std::collections::BTreeMap::new();
    if let Some(earlier) = previous
        .and_then(|value| value.get("recentWork"))
        .and_then(Value::as_array)
    {
        for event in earlier {
            if let Some(sequence) = event["sequence"].as_u64() {
                events.insert(sequence, event.clone());
            }
        }
    }
    for event in observation["events"].as_array().into_iter().flatten() {
        let (Some(sequence), Some(kind), Some(target)) = (
            event["sequence"]
                .as_u64()
                .filter(|sequence| *sequence > 0 && *sequence < 1 << 53),
            event["type"].as_str(),
            event["detail"]["target"].as_str(),
        ) else {
            continue;
        };
        if !matches!(
            kind,
            "garden.place"
                | "garden.update"
                | "garden.remove"
                | "node.place"
                | "node.update"
                | "node.remove"
                | "bridge.set"
        ) || !(target == "bridge"
            || ["garden-", "node-"].iter().any(|prefix| {
                target.strip_prefix(prefix).is_some_and(|suffix| {
                    !suffix.is_empty()
                        && suffix.len() <= 40
                        && suffix
                            .bytes()
                            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == b'-')
                })
            }))
        {
            continue;
        }
        let mut summary = json!({"sequence":sequence,"type":kind,"target":target});
        let detail = &event["detail"];
        let entity = detail
            .get("node")
            .filter(|v| !v.is_null())
            .unwrap_or(&detail["entity"]);
        if let Some(revision) = entity["revision"].as_i64() {
            summary["revision"] = json!(revision);
        }
        events.insert(sequence, summary);
    }
    let mut recent_work: Vec<_> = events.into_values().rev().take(8).collect();
    recent_work.reverse();
    Map::from_iter([
        (
            "place".into(),
            select(
                &observation["place"],
                &["id", "title", "level", "house", "exhibitRevision"],
            ),
        ),
        (
            "selection".into(),
            json!({
                "object":observation["referredRoomObject"], "workstation":observation["referredWorkstation"],
                "visit":observation["referredRoomVisit"], "worktable":observation["referredWorktable"],
                "history":observation["selectedActivity"],
            }),
        ),
        (
            "pose".into(),
            cell.map_or(Value::Null, |cell| {
                json!({
                    "kind":"client-reported-position","cellMeters":0.5,"cell":cell
                })
            }),
        ),
        (
            "work".into(),
            json!({
                "activity":activity, "objects":observation["place"]["objects"],
                "contents":observation["place"]["contents"], "focus":focus,
                "focusPartial":observation["source"]["omissions"]["focus"].as_u64().unwrap_or(0)>0,
                "nodes":nodes, "entities":observation["entities"],
            }),
        ),
        ("recentWork".into(), json!(recent_work)),
    ])
}
