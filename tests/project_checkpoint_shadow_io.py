#!/usr/bin/env python3
"""Exercise the real owner controller and canonical source reader with a fake Codex."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from conversation_routing_io import CanonicalRouting


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def select_project(journey, *, paginate=False):
    topic, = journey.row("SELECT id FROM sessions WHERE thread_id=7")[0]
    adopted = journey.read("topics", "workspace", "adopt", "7", str(topic))["result"]
    assert adopted["folder_ready"], adopted
    folder = Path(adopted["conversation_folder"])
    def prepare_checkout(name, project, repository=None):
        checkout = folder / name
        checkout.mkdir()
        git(checkout, "init", "--object-format=sha1")
        (checkout / f"{name}.txt").write_text(f"A shared project file for {name}.\n")
        git(checkout, "add", f"{name}.txt")
        git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "First draft")
        git(checkout, "config", "--local", "daimon.project-id", repository or project)
        link = {"project": project, "locator": f"git:local:{repository or project}",
                "commit": git(checkout, "rev-parse", "HEAD"), "label": name.capitalize()}
        if repository:
            link["repository"] = repository
        return link

    story = str(uuid.uuid4())
    link = prepare_checkout("story", story)
    work = [
        {"kind": "decision", "text": "Keep the main character's name."},
        {"kind": "dependency", "text": "Wait for the illustrator's draft."},
        {"kind": "next_action", "text": "Review the second scene in the shared draft."},
    ]
    other_links = [("illustrations", prepare_checkout("illustrations", story, str(uuid.uuid4()))),
                   ("notes", prepare_checkout("notes", str(uuid.uuid4())))]

    if paginate:
        checkout = folder / "story"
        def commit_draft(message):
            git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", message)
            return git(checkout, "rev-parse", "HEAD")

        next_link = {**link, "commit": commit_draft("Second draft")}
        unregistered_commit = commit_draft("Private working draft")
        other_links.extend((f"extra-{n}", prepare_checkout(f"extra-{n}", str(uuid.uuid4())))
                           for n in range(7))
    binding = journey.read("presentation", "list", "0", "0")["result"]["binding"]

    def dispatch(number, selector, thread, text, *, relation="new", requests=()):
        original = {"id": str(uuid.uuid4()), "binding": binding, "text": text}
        journey.read("input", "submit-human", json.dumps(original))
        journey.wait(lambda: journey.row(
            "SELECT phase FROM conversation_inputs WHERE id=?", (original["id"],)
        ) == [("accepted",)])
        journey.call(f"route-shadow-dispatch-{number}", "dispatch", {
            "input_ref": original["id"],
            "destinations": [{"selector": selector, "relation": relation, "requests": list(requests)}],
        })
        journey.wait(lambda: len(journey.instructions(thread)) == number
                     and journey.instructions(thread)[-1][1] == "accepted")

    def shadow(thread, ident, args, *, ok=True):
        native, = journey.row("SELECT codex_thread_id FROM sessions WHERE thread_id=?", (thread,))[0]
        journey.wait(lambda: native in journey.workers)
        send = next(send for selected, send in journey.clients.values() if selected == native)
        call = f"route-shadow-{ident}"
        send({"id": call, "method": "item/tool/call", "params": {
            "threadId": native, "turnId": journey.workers[native], "callId": call,
            "tool": "interaction_controller",
            "arguments": {"operation": "project_checkpoint_shadow", "arguments": args},
        }})
        journey.wait(lambda: call in journey.tool_results)
        result = journey.tool_results[call]
        assert result["success"] is ok, result
        return json.loads(result["contentItems"][0]["text"]) if ok else None

    dispatch(1, "Alpha", 7, "Record the selected revision.")
    citations = "\n".join("Project link: " + json.dumps(item) for item in
                          [link, *(other for _, other in other_links)])
    citations += "\nProject checkpoint: " + json.dumps({"link": link, "work": work})
    if paginate:
        citations += "\nProject checkpoint: " + json.dumps({"link": next_link, "work": work})
    journey.answer_worker(7, "Staged the selected repo.\n" + citations)
    journey.wait(lambda: journey.row("SELECT busy FROM sessions WHERE thread_id=7") == [(0,)])
    page = journey.read("presentation", "list", "0", "0")["result"]
    result = next(item for item in page["items"] if item["kind"] == "worker_result")
    source = {"kind": "conversation", "source": result["id"], "revision": result["revision"]}

    dispatch(2, "Alpha", 7, "Prepare the project's shadow checkpoint.")
    workspace = shadow(7, "workspace", {"action": "workspace"})["workspace"]
    assert workspace
    delta = {"operation": str(uuid.uuid4()), "expected_revision": 0, "workspace": workspace,
             "link": link, "sources": [source]}
    apply = {"action": "apply", "checkout": "story", "delta": {**delta, "work": work}}
    unsupported = [{**work[0], "text": "Rename the main character."}, *work[1:]]
    shadow(7, "unsupported-work", {**apply, "delta": {**delta, "work": unsupported}}, ok=False)
    queried_before = journey.row("SELECT count(*) FROM interaction_instructions")
    accepted = shadow(7, "accept", apply)
    assert accepted["status"] == "accepted", accepted
    assert accepted["checkpoint"]["delta"] == apply["delta"]
    reused = shadow(7, "changed-work-under-same-key", {
        **apply, "delta": {**delta, "work": unsupported},
    })
    assert reused == {"status": "conflict", "revision": 1}, reused
    shadow(7, "omitted-work", {
        **apply, "delta": {**delta, "operation": str(uuid.uuid4()), "expected_revision": 1},
    }, ok=False)
    (folder / "archive").mkdir()
    (folder / "story").rename(folder / "archive/moved")
    retry = shadow(7, "repeat", {**apply, "checkout": "archive/moved"})
    assert retry == {**accepted, "status": "retained"}, retry
    read = shadow(7, "read", {"action": "read", "workspace": workspace, "checkout": "archive/moved"})
    assert read == accepted["checkpoint"], read
    assert journey.row("SELECT count(*) FROM interaction_instructions") == queried_before
    selections = [{"project": story, "repository": story, "revision": 1,
                   "checkout": "archive/moved"}]
    repositories = [{"revision": 1, "link": link, "checkout": "archive/moved",
                     "sources": [source], "work": work}]
    for revision, (folder_name, other) in enumerate(other_links, start=2):
        proposal = {**delta, "operation": str(uuid.uuid4()),
                    "expected_revision": revision - 1, "link": other}
        result_other = shadow(7, f"accept-{revision}", {
            "action": "apply", "checkout": folder_name, "delta": proposal,
        })
        assert result_other["checkpoint"]["revision"] == revision, result_other
        selections.append({"project": other["project"],
                           "repository": other.get("repository", other["project"]),
                           "revision": revision, "checkout": folder_name})
        repositories.append({"revision": revision, "link": other,
                             "checkout": folder_name, "sources": [source]})
    count = len(repositories)
    visible = shadow(7, "workspace-links", {"action": "projects", "workspace": workspace})
    assert visible["revision"] == count, visible
    assert visible["links"] == [
        {"revision": row["revision"], "link": row["link"]} for row in list(reversed(repositories))[:8]
    ], visible

    def room_page(cursor=None, **selection):
        target = {"chat_id": 100, "thread_id": 7, **selection, **({"cursor": cursor} if cursor else {})}
        room = journey.read("input", "topic-projects", json.dumps(target))["result"]
        assert room["schema"] == "daimon.topic-projects/v1"
        return room

    room = room_page()
    projected = [
        {"project": item["project"], "repository": item.get("repository", item["project"]),
         "label": item["label"], "commit": item["commit"]}
        for item in [row["link"] for row in reversed(repositories)]
    ]
    assert room["repositories"] == projected[:8] and not room["restarted"], room
    detail = room_page(project=story, repository=story)
    assert detail["project"] == story and detail["next"] is None, detail
    assert detail["repositories"] == [row for row in projected if row["project"] == story], detail
    if paginate:
        second = room_page(room["next"])
        assert second["repositories"] == projected[8:] and second["next"] is None, second
        old = room_page("1.1")
        assert old["restarted"] and old["repositories"] == projected[:8], old
    else:
        assert room["next"] is None
    for selection_row, expected in zip(selections, repositories, strict=True):
        result_row = shadow(7, f"read-repository-{expected['revision']}", {
            "action": "read", "workspace": workspace, "checkout": selection_row["checkout"],
            "project": selection_row["project"], "repository": selection_row["repository"],
        })
        assert result_row["revision"] == expected["revision"], result_row
        assert result_row["delta"]["link"] == expected["link"], result_row
        assert result_row["delta"].get("work") == expected.get("work"), result_row
    assert journey.row("SELECT revision FROM project_checkpoint_deltas") == [(n,) for n in range(1,count+1)]

    finished, unfinished = [row[0] for row in journey.instructions(7)]
    selected = shadow(7, "select", {
        "action": "select_recovery", "workspace": workspace, "projects": selections[:3],
        "effects": [finished, unfinished],
    })
    assert selected["selected"] and selected["revisions"] == [1, 2, 3], selected
    resolved, unresolved = selected["effects"]
    assert resolved["original"] == finished and resolved["result"], selected
    assert resolved["disposition"] == "result_retained" and resolved["requestCompleted"], selected
    assert unresolved == {
        "original": unfinished, "transport": "accepted", "result": None, "disposition": "unresolved", "requestCompleted": False,
    }, selected
    assert journey.row("SELECT count(*) FROM interaction_instructions") == queried_before
    if paginate:
        advanced = shadow(7, "advance-story", {
            **apply, "checkout": "archive/moved",
            "delta": {**delta, "operation": str(uuid.uuid4()),
                      "expected_revision": count, "link": next_link, "work": work},
        })
        assert advanced["status"] == "accepted", advanced
        assert advanced["checkpoint"]["revision"] == count + 1, advanced
        repositories.append({"revision": count + 1, "link": next_link, "checkout": "archive/moved"})
        exact = {"action": "read", "workspace": workspace, "checkout": "archive/moved",
                 "project": story, "repository": story}
        latest = shadow(7, "latest-story", exact)
        assert latest == advanced["checkpoint"], latest
        assert shadow(7, "old-story", {**exact, "commit": link["commit"]}) == accepted["checkpoint"]
        assert shadow(7, "unregistered-object", {**exact, "commit": unregistered_commit}) is None
        assert shadow(7, "different-repository", {
            **exact, "repository": other_links[0][1]["repository"], "commit": link["commit"],
        }) is None
        shadow(7, "wrong-checkout", {**exact, "checkout": "illustrations", "commit": link["commit"]}, ok=False)
        shadow(7, "abbreviated-commit", {**exact, "commit": link["commit"][:12]}, ok=False)
        shadow(7, "unscoped-commit", {**exact, "repository": None, "commit": link["commit"]}, ok=False)
        assert journey.row("SELECT count(*) FROM interaction_instructions") == queried_before
    return repositories, selected["effects"], workspace, apply, result, dispatch, shadow


def run(binary):
    journey = CanonicalRouting(binary)
    try:
        journey.start()
        for topic in (1, 7, 8):
            journey.admit("Seed the owned native context.", topic=topic)
            journey.wait(lambda: journey.has("Initial goal turn delivered.", topic))
            journey.idle()
        journey.stop()
        root = journey.root / "topic-folders"
        root.mkdir(mode=0o700)
        config = journey.config.read_text().replace(
            "[interaction]\n",
            f"[interaction]\ntopic_workspace_root={json.dumps(str(root))}\n",
            1,
        )
        journey.config.write_text(config + journey.target_config)
        journey.start()
        journey.wait_control_socket(journey.socket)
        journey.routing = True
        repositories, _, workspace, apply, result, dispatch, shadow = select_project(journey, paginate=True)
        dispatch(3, "Alpha", 7, "Correct the first iteration: withdraw the old revision citation.",
                 relation="amends", requests=result["request_ids"])
        corrected = journey.read("presentation", "list", "0", "0")["result"]["items"]
        assert all(item["id"] != result["id"] or not item["current"] for item in corrected)
        assert shadow(7, "still-owned", {"action": "workspace"})["workspace"] == workspace
        corrected_count = journey.row("SELECT count(*) FROM interaction_instructions")
        shadow(7, "revoked-read", {"action": "read", "workspace": workspace, "checkout": "archive/moved",
                                    "project": apply["delta"]["link"]["project"]}, ok=False)
        shadow(7, "revoked-old-story", {"action": "read", "workspace": workspace,
                 "checkout": "archive/moved", "project": apply["delta"]["link"]["project"],
                 "repository": apply["delta"]["link"]["project"], "commit": apply["delta"]["link"]["commit"]},
               ok=False)
        shadow(7, "revoked-repeat", {**apply, "checkout": "archive/moved"}, ok=False)
        room = journey.read("input", "topic-projects", json.dumps({"chat_id":100,"thread_id":7}))["result"]
        assert room["repositories"] == [], room
        assert journey.row("SELECT count(*) FROM interaction_instructions") == corrected_count
        assert journey.row("SELECT revision FROM project_checkpoint_deltas") == [(n,) for n in range(1,len(repositories)+1)]
        print("PASS owned Gateway controller verified canonical conversation evidence and paged repository links; checkout move, historical commit read, exact repeat and source correction caused no duplicate dispatch or extra model call.")
    finally:
        journey.close()


if __name__ == "__main__":
    run(str(Path(sys.argv[1]).resolve()))
