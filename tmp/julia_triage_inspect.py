#!/usr/bin/env python3
import base64
import concurrent.futures
import json
import os
import subprocess
import sys

ACCOUNT = "julia.joy.jennings@gmail.com"


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


def headers(msg):
    return {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in msg.get("payload", {}).get("headers", [])
    }


def decode_part(part):
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    texts = []
    if data and (mime.startswith("text/plain") or mime.startswith("text/html")):
        try:
            texts.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace"))
        except Exception:
            pass
    for child in part.get("parts", []) or []:
        texts.extend(decode_part(child))
    return texts


def fetch(item):
    msg = gws("users messages", "get", {"userId": "me", "id": item["id"], "format": "full"})
    h = headers(msg)
    text = "\n".join(decode_part(msg.get("payload", {})))
    compact = " ".join(text.split())
    return {
        "id": msg.get("id", ""),
        "threadId": msg.get("threadId", ""),
        "labels": msg.get("labelIds", []),
        "from": h.get("from", ""),
        "to": h.get("to", ""),
        "subject": h.get("subject", ""),
        "date": h.get("date", ""),
        "messageIdHeader": h.get("message-id", ""),
        "references": h.get("references", ""),
        "replyTo": h.get("reply-to", ""),
        "listUnsubscribe": h.get("list-unsubscribe", ""),
        "snippet": (msg.get("snippet") or compact)[:500],
        "bodyPreview": compact[:1200],
    }


def main():
    labels = gws("users labels", "list", {"userId": "me"}).get("labels", [])
    promos = paginate(
        "users messages",
        "list",
        {"userId": "me", "q": "in:inbox category:promotions is:unread older_than:3d"},
        "messages",
    )
    unread = paginate(
        "users messages",
        "list",
        {"userId": "me", "q": "is:unread in:inbox"},
        "messages",
    )
    ids = {m["id"]: m for m in promos + unread}
    full = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        futures = {ex.submit(fetch, m): m["id"] for m in ids.values()}
        for fut in concurrent.futures.as_completed(futures):
            try:
                full.append(fut.result())
            except Exception as e:
                errors.append({"id": futures[fut], "error": str(e)[:200]})
    full.sort(key=lambda x: x["date"])
    print(json.dumps({
        "labels": [{"id": x.get("id"), "name": x.get("name")} for x in labels],
        "promoIds": [x["id"] for x in promos],
        "unreadIds": [x["id"] for x in unread],
        "messages": full,
        "errors": errors,
    }))


if __name__ == "__main__":
    main()
