#!/usr/bin/env python3
import base64
import concurrent.futures
import html
import json
import os
import re
import subprocess
import time
from pathlib import Path

ACCOUNT = "julia.joy.jennings@gmail.com"
OUT = Path("/Users/dbochman/.openclaw/workspace/tmp/julia_triage_20260726_snapshot.json")


def gws(resource, method, params=None, body=None, retry=True):
    params = dict(params or {})
    params["userId"] = "me"
    cmd = ["gws", "gmail", "users", resource, method, "--params",
           json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_ACCOUNT"] = ACCOUNT
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode and retry and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(resource, method, params, body, retry=False)
    if proc.returncode:
        raise RuntimeError(combined.strip()[:500])
    data = json.loads(proc.stdout or "{}")
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(json.dumps(data["error"], separators=(",", ":"))[:500])
    return data


def list_all(resource, query=None):
    out = []
    token = None
    while True:
        params = {"maxResults": 100}
        if query is not None:
            params["q"] = query
        if token:
            params["pageToken"] = token
        page = gws(resource, "list", params)
        out.extend(page.get(resource, []) or [])
        token = page.get("nextPageToken")
        if not token:
            return out


def header(message, name):
    for item in message.get("payload", {}).get("headers", []) or []:
        if item.get("name", "").lower() == name.lower():
            return item.get("value", "")
    return ""


def decode_part(part):
    out = []
    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        try:
            value = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            if mime == "text/html":
                value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
                value = re.sub(r"<[^>]+>", " ", value)
                value = html.unescape(value)
            out.append(value)
        except Exception:
            pass
    for child in part.get("parts", []) or []:
        out.extend(decode_part(child))
    return out


def fetch(item):
    message = gws("messages", "get", {"id": item["id"], "format": "full"})
    text = re.sub(r"\s+", " ", " ".join(decode_part(message.get("payload") or {}))).strip()
    return {
        "id": message.get("id", ""),
        "threadId": message.get("threadId", ""),
        "labelIds": message.get("labelIds", []) or [],
        "from": header(message, "From"),
        "to": header(message, "To"),
        "subject": header(message, "Subject"),
        "date": header(message, "Date"),
        "messageIdHeader": header(message, "Message-ID"),
        "references": header(message, "References"),
        "inReplyTo": header(message, "In-Reply-To"),
        "replyTo": header(message, "Reply-To"),
        "listUnsubscribe": header(message, "List-Unsubscribe"),
        "snippet": message.get("snippet", ""),
        "text": text[:5000],
    }


def main():
    labels = gws("labels", "list").get("labels", []) or []
    promo = list_all("messages", "in:inbox category:promotions is:unread older_than:3d")
    unread = list_all("messages", "is:unread in:inbox")
    drafts = list_all("drafts")
    items = {item["id"]: item for item in promo + unread}
    messages = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, item): item["id"] for item in items.values()}
        for future in concurrent.futures.as_completed(futures):
            try:
                messages.append(future.result())
            except Exception as exc:
                errors.append({"id": futures[future], "error": str(exc)[:200]})
    order = {item["id"]: index for index, item in enumerate(unread)}
    messages.sort(key=lambda item: order.get(item["id"], len(order)))
    payload = {
        "labels": [{"id": item.get("id"), "name": item.get("name")} for item in labels],
        "promoIds": [item["id"] for item in promo],
        "unreadIds": [item["id"] for item in unread],
        "draftThreadIds": sorted({
            (item.get("message") or {}).get("threadId")
            for item in drafts
            if (item.get("message") or {}).get("threadId")
        }),
        "messages": messages,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False))
    print(json.dumps({
        "promo": len(promo),
        "unread": len(unread),
        "draftThreads": len(payload["draftThreadIds"]),
        "fetched": len(messages),
        "errors": errors,
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
