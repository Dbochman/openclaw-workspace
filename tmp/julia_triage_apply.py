#!/usr/bin/env python3
import json
import os
import subprocess

ACCOUNT = "julia.joy.jennings@gmail.com"
DATE = "2026-07-25"
LABEL_NAMES = [
    "OpenClaw/Urgent",
    "OpenClaw/Action",
    "OpenClaw/FYI",
    "OpenClaw/Financial",
    "OpenClaw/Shopping",
    "OpenClaw/Newsletters",
    "OpenClaw/Social",
]

CLASSIFICATIONS = {
    "OpenClaw/Urgent": [
        "19f95ff8b0ec5724",
        "19f95ff88d5d5e62",
        "19f91484a426741e",
    ],
    "OpenClaw/Financial": ["19f940de413ff9ce"],
    "OpenClaw/Shopping": ["19f93e986ca6ce5a"],
    "OpenClaw/Newsletters": [
        "19f9401a613a643b",
        "19f93c558f0a7e7f",
        "19f94358a1c5f97b",
        "19f94f760492d7de",
        "19f9681b246274e6",
    ],
}

ATTENTION = [
    {
        "messageId": "19f95ff8b0ec5724",
        "threadId": "19f95ff8b0ec5724",
        "from": "Reolink <noreply@mail.reolink.com>",
        "subject": "We Noticed a New Login",
        "reason": "A new password login was reported for the Reolink account; Julia should verify it was expected.",
        "deadline": "",
        "draftStatus": "none",
    },
    {
        "messageId": "19f95ff88d5d5e62",
        "threadId": "19f95ff88d5d5e62",
        "from": "Reolink <noreply@mail.reolink.com>",
        "subject": "Reolink Account Created.",
        "reason": "A Reolink account-creation notice needs verification that Julia expected the new account.",
        "deadline": "",
        "draftStatus": "none",
    },
    {
        "messageId": "19f91484a426741e",
        "threadId": "19f91484a426741e",
        "from": '"T. Rowe Price" <do-not-reply@troweprice.com>',
        "subject": "T. Rowe Price - Login and Security Information Alert",
        "reason": "T. Rowe Price reports that account access was suspended and a password reset is required.",
        "deadline": "",
        "draftStatus": "none",
    },
]


def gws(resource, method, params, body=None):
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_ACCOUNT"] = ACCOUNT
    cmd = ["gws", "gmail", *resource.split(), method, "--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    p = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    data = json.loads(p.stdout or "{}")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(json.dumps(data["error"]))
    return data


def paginate(resource, method, params, key):
    out = []
    token = None
    while True:
        p = dict(params)
        p["maxResults"] = 100
        if token:
            p["pageToken"] = token
        data = gws(resource, method, p)
        out.extend(data.get(key, []))
        token = data.get("nextPageToken")
        if not token:
            return out


def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def batch_modify(ids, add_ids, remove_ids):
    for batch in chunks(ids, 1000):
        gws(
            "users messages",
            "batchModify",
            {"userId": "me"},
            {"ids": batch, "addLabelIds": add_ids, "removeLabelIds": remove_ids},
        )


def result_template():
    return {
        "schemaVersion": 1,
        "status": "ok",
        "date": DATE,
        "processed": 0,
        "markedRead": 0,
        "leftUnread": 0,
        "draftsCreated": 0,
        "draftsExisting": 0,
        "archived": 0,
        "trashed": 0,
        "unreadAfter": [],
        "attention": [],
        "errors": [],
    }


def main():
    out = result_template()
    successful = set()
    marked_read = set()
    deliberately_unread = set()
    archived = set()
    failed_ids = set()

    try:
        labels_data = gws("users labels", "list", {"userId": "me"})
        label_map = {x.get("name"): x.get("id") for x in labels_data.get("labels", [])}
        for name in LABEL_NAMES:
            if not label_map.get(name):
                created = gws(
                    "users labels",
                    "create",
                    {"userId": "me"},
                    {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                )
                label_map[name] = created["id"]
    except Exception as e:
        out["status"] = "partial"
        out["errors"].append("label setup failed: " + str(e)[:240])
        print(json.dumps(out, separators=(",", ":")))
        return

    primary_ids = [label_map[name] for name in LABEL_NAMES]
    for primary_name, ids in CLASSIFICATIONS.items():
        primary_id = label_map[primary_name]
        remove = [x for x in primary_ids if x != primary_id]
        add = [primary_id]
        if primary_name == "OpenClaw/Urgent":
            add.append("STARRED")
        else:
            remove.append("UNREAD")
        try:
            batch_modify(ids, add, remove)
            successful.update(ids)
            if primary_name == "OpenClaw/Urgent":
                deliberately_unread.update(ids)
            else:
                marked_read.update(ids)
        except Exception as e:
            failed_ids.update(ids)
            out["errors"].append(
                f"classification/read-state failed for {','.join(ids)}: {str(e)[:180]}"
            )

    routine_names = [
        "OpenClaw/FYI",
        "OpenClaw/Financial",
        "OpenClaw/Shopping",
        "OpenClaw/Newsletters",
        "OpenClaw/Social",
    ]
    for name in routine_names:
        try:
            listed = paginate(
                "users messages",
                "list",
                {"userId": "me", "q": f'is:read in:inbox label:"{name}"'},
                "messages",
            )
            snapshot = [x["id"] for x in listed]
        except Exception as e:
            out["errors"].append(f"archive list failed for {name}: {str(e)[:200]}")
            continue
        eligible = []
        for mid in snapshot:
            try:
                msg = gws(
                    "users messages",
                    "get",
                    {"userId": "me", "id": mid, "format": "full"},
                )
                labs = set(msg.get("labelIds", []))
                if (
                    "INBOX" in labs
                    and "UNREAD" not in labs
                    and "STARRED" not in labs
                    and label_map["OpenClaw/Urgent"] not in labs
                    and label_map["OpenClaw/Action"] not in labs
                ):
                    eligible.append(mid)
            except Exception as e:
                out["errors"].append(f"archive inspection failed for {mid}: {str(e)[:180]}")
        if eligible:
            try:
                batch_modify(eligible, [], ["INBOX"])
                archived.update(eligible)
            except Exception as e:
                out["errors"].append(
                    f"archive mutation failed for {name}: {str(e)[:200]}"
                )

    try:
        final_unread = paginate(
            "users messages",
            "list",
            {"userId": "me", "q": "is:unread in:inbox"},
            "messages",
        )
        out["unreadAfter"] = [x["id"] for x in final_unread]
    except Exception as e:
        out["errors"].append("final unread query failed: " + str(e)[:220])

    out["processed"] = len(successful)
    out["markedRead"] = len(marked_read)
    out["leftUnread"] = len(deliberately_unread | failed_ids)
    out["archived"] = len(archived)
    out["attention"] = [x for x in ATTENTION if x["messageId"] in successful]
    if out["errors"]:
        out["status"] = "partial"
    print(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
