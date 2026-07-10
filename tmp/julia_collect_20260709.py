#!/usr/bin/env python3
import concurrent.futures
import json
import os
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
ENV = dict(os.environ, GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)


def gws(parts, params=None, body=None, retry=True):
    params = dict(params or {})
    params.setdefault("userId", "me")
    cmd = ["gws", "gmail"] + parts + ["--params", json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    p = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    combined = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode and retry and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(parts, params, body, retry=False)
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


def get_full(mid):
    try:
        msg = gws(["users", "messages", "get"], {"userId": "me", "id": mid, "format": "full"})
        return {"ok": True, "message": msg}
    except Exception as exc:
        return {"ok": False, "id": mid, "error": str(exc)[:300]}


labels = gws(["users", "labels", "list"], {"userId": "me"})
spam = list_all(["users", "messages", "list"], "in:inbox category:promotions is:unread older_than:3d")
unread = list_all(["users", "messages", "list"], "is:unread in:inbox")
drafts = list_all(["users", "drafts", "list"], None, "drafts")
all_ids = list(dict.fromkeys([x["id"] for x in spam + unread]))
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    full = list(pool.map(get_full, all_ids))
print(json.dumps({"labels": labels, "spam": spam, "unread": unread, "drafts": drafts, "full": full}, ensure_ascii=False))
