#!/usr/bin/env python3
import base64
import concurrent.futures
import json
import os
import re
import subprocess
from pathlib import Path

ACCOUNT = "julia.joy.jennings@gmail.com"
ENV = dict(os.environ, GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)
LABELS = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI",
    "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]


def gws(parts, params=None, body=None):
    params = dict(params or {})
    params.setdefault("userId", "me")
    cmd = ["gws", "gmail"] + parts + ["--params", json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    p = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    combined = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode:
        raise RuntimeError(combined[:500] or "gws command failed")
    out = json.loads(p.stdout or "{}")
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(str(out["error"])[:500])
    return out


def list_all(parts, q=None, key="messages"):
    items, token = [], None
    while True:
        params = {"userId": "me", "maxResults": 100}
        if q is not None:
            params["q"] = q
        if token:
            params["pageToken"] = token
        out = gws(parts, params)
        items.extend(out.get(key, []) or [])
        token = out.get("nextPageToken")
        if not token:
            return items


def ensure_labels():
    data = gws(["users", "labels", "list"], {"userId": "me"})
    by_name = {item.get("name"): item.get("id") for item in data.get("labels", [])}
    for name in LABELS:
        if not by_name.get(name):
            made = gws(
                ["users", "labels", "create"],
                {"userId": "me"},
                {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            )
            by_name[name] = made["id"]
    return {name: by_name[name] for name in LABELS}


def decode(data):
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


def body_text(payload):
    found = []
    def walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime in ("text/plain", "text/html"):
            text = decode(data)
            if mime == "text/html":
                text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
                text = re.sub(r"<[^>]+>", " ", text)
            found.append(text)
        for child in part.get("parts", []) or []:
            walk(child)
    walk(payload or {})
    return re.sub(r"\s+", " ", " ".join(found)).strip()[:5000]


def fetch(mid):
    try:
        msg = gws(["users", "messages", "get"], {"userId": "me", "id": mid, "format": "full"})
        hdr = {h.get("name", "").lower(): h.get("value", "") for h in (msg.get("payload", {}).get("headers", []) or [])}
        return {
            "ok": True, "id": mid, "threadId": msg.get("threadId", ""),
            "from": hdr.get("from", ""), "to": hdr.get("to", ""),
            "subject": hdr.get("subject", ""), "date": hdr.get("date", ""),
            "messageIdHeader": hdr.get("message-id", ""), "references": hdr.get("references", ""),
            "labels": msg.get("labelIds", []), "snippet": msg.get("snippet", ""),
            "body": body_text(msg.get("payload", {})),
        }
    except Exception as exc:
        return {"ok": False, "id": mid, "error": str(exc)[:300]}


label_map = ensure_labels()
spam = list_all(["users", "messages", "list"], "in:inbox category:promotions is:unread older_than:3d")
unread = list_all(["users", "messages", "list"], "is:unread in:inbox")
drafts = list_all(["users", "drafts", "list"], None, "drafts")
ids = list(dict.fromkeys([x["id"] for x in spam + unread]))
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    full = list(pool.map(fetch, ids))
result = {"labels": label_map, "spam": spam, "unread": unread, "drafts": drafts, "full": full}
Path("tmp/julia_collect_20260714.json").write_text(json.dumps(result, ensure_ascii=False))
print(json.dumps({"spam": len(spam), "unread": len(unread), "drafts": len(drafts), "fetched": sum(1 for x in full if x.get("ok")), "failed": sum(1 for x in full if not x.get("ok"))}))
