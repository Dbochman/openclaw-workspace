#!/usr/bin/env python3
import json
import os
import subprocess

ACCOUNT = "julia.joy.jennings@gmail.com"
ENV = dict(os.environ, GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)
DATE = "2026-07-14"
LABELS = {
    "OpenClaw/Urgent": "Label_8", "OpenClaw/Action": "Label_9",
    "OpenClaw/FYI": "Label_10", "OpenClaw/Financial": "Label_11",
    "OpenClaw/Shopping": "Label_12", "OpenClaw/Newsletters": "Label_13",
    "OpenClaw/Social": "Label_14",
}
PRIMARY = set(LABELS.values())
errors = [
    "fetch 19f5ef65e312c2c0: No credentials provided",
    "fetch 19f5b59bf0d4b3d7: No credentials provided",
    "fetch 19f5b41a11fc49e6: No credentials provided",
]


def gws(parts, params=None, body=None):
    params = dict(params or {})
    params.setdefault("userId", "me")
    cmd = ["gws", "gmail"] + parts + ["--params", json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    proc = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode:
        raise RuntimeError(combined[:300] or "gws command failed")
    out = json.loads(proc.stdout or "{}")
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(str(out["error"])[:300])
    return out


def list_all(q):
    items, token = [], None
    while True:
        params = {"userId": "me", "q": q, "maxResults": 100}
        if token:
            params["pageToken"] = token
        data = gws(["users", "messages", "list"], params)
        items.extend(data.get("messages", []) or [])
        token = data.get("nextPageToken")
        if not token:
            return [item["id"] for item in items]


def batch_modify(ids, add=None, remove=None):
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        body = {"ids": chunk}
        if add:
            body["addLabelIds"] = list(add)
        if remove:
            body["removeLabelIds"] = list(remove)
        gws(["users", "messages", "batchModify"], {"userId": "me"}, body)


classified = {
    "OpenClaw/Newsletters": [
        "19f5db4e76cf5acb", "19f5d5b00fe256cf", "19f5b8fb7c08bd82",
    ],
    "OpenClaw/Social": ["19f5b74b6ed9f765", "19f592d927ab77bd"],
    "OpenClaw/Urgent": [
        "19f562fa3f53573b", "19f562f3f2a3e671", "19f562ee0681fe8e",
    ],
}
routine_read = [
    "19f5db4e76cf5acb", "19f5d5b00fe256cf", "19f5b8fb7c08bd82",
    "19f5b74b6ed9f765",
]
attention = [
    {
        "messageId": "19f592d927ab77bd", "threadId": "19f592d927ab77bd",
        "from": "Dylan Bochman <dylanbochman@gmail.com>",
        "subject": "Invitation: Grill @ Chill @ Nicks New House @ Sun Jul 19, 2026 12:30pm - 2:15pm (EDT) (Julia Joy Jennings)",
        "reason": "Calendar invitation for July 19 requires Julia to review or RSVP.",
        "deadline": "", "draftStatus": "none",
    },
    {
        "messageId": "19f562fa3f53573b", "threadId": "19f562fa3f53573b",
        "from": "Samsung account <sa.noreply@samsung-mail.com>",
        "subject": "2-step verification settings changed",
        "reason": "Unconfirmed Samsung account security-setting change requires review.",
        "deadline": "", "draftStatus": "none",
    },
    {
        "messageId": "19f562f3f2a3e671", "threadId": "19f562f3f2a3e671",
        "from": "Samsung account <sa.noreply@samsung-mail.com>",
        "subject": "New sign-in to your Samsung account",
        "reason": "Unconfirmed new Samsung account sign-in requires review.",
        "deadline": "", "draftStatus": "none",
    },
    {
        "messageId": "19f562ee0681fe8e", "threadId": "19f562ee0681fe8e",
        "from": "Samsung account <sa.noreply@samsung-mail.com>",
        "subject": "Your password has been reset.",
        "reason": "Unconfirmed Samsung account password reset requires review.",
        "deadline": "", "draftStatus": "none",
    },
]

marked_read = 0
archived = 0
successful = set()
for label_name, ids in classified.items():
    selected = LABELS[label_name]
    add = [selected]
    if label_name == "OpenClaw/Urgent":
        add.append("STARRED")
    try:
        batch_modify(ids, add=add, remove=PRIMARY - {selected})
        successful.update(ids)
    except Exception as exc:
        errors.append(f"label {label_name}: {str(exc)[:150]}")

to_read = [mid for mid in routine_read if mid in successful]
if to_read:
    try:
        batch_modify(to_read, remove=["UNREAD"])
        marked_read = len(to_read)
    except Exception as exc:
        errors.append(f"mark read: {str(exc)[:150]}")

# Fully snapshot all five routine-label inbox result sets before any archive mutation.
routine_names = [
    "OpenClaw/FYI", "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]
archive_snapshots = {}
for name in routine_names:
    try:
        archive_snapshots[name] = list_all(f'is:read in:inbox label:"{name}"')
    except Exception as exc:
        archive_snapshots[name] = []
        errors.append(f"archive list {name}: {str(exc)[:150]}")

archive_candidates = list(dict.fromkeys(mid for ids in archive_snapshots.values() for mid in ids))
archive_ok = []
for mid in archive_candidates:
    try:
        msg = gws(["users", "messages", "get"], {"userId": "me", "id": mid, "format": "full"})
        labels = set(msg.get("labelIds", []))
        if "UNREAD" in labels or "INBOX" not in labels:
            continue
        if labels & {LABELS["OpenClaw/Urgent"], LABELS["OpenClaw/Action"], "STARRED"}:
            continue
        if not labels & {LABELS[name] for name in routine_names}:
            continue
        archive_ok.append(mid)
    except Exception as exc:
        errors.append(f"archive fetch {mid}: {str(exc)[:150]}")

if archive_ok:
    try:
        batch_modify(archive_ok, remove=["INBOX"])
        archived = len(set(archive_ok))
    except Exception as exc:
        errors.append(f"archive: {str(exc)[:150]}")

try:
    unread_after = list_all("is:unread in:inbox")
except Exception as exc:
    unread_after = []
    errors.append(f"final unread list: {str(exc)[:150]}")

result = {
    "schemaVersion": 1,
    "status": "partial" if errors else "ok",
    "date": DATE,
    "processed": 8,
    "markedRead": marked_read,
    "leftUnread": len(unread_after),
    "draftsCreated": 0,
    "draftsExisting": 0,
    "archived": archived,
    "trashed": 0,
    "unreadAfter": unread_after,
    "attention": attention,
    "errors": errors,
}
print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
