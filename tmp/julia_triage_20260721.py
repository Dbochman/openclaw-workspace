#!/usr/bin/env python3
import base64
import email.utils
import html
import json
import os
import re
import subprocess
import sys
import time
from email.message import EmailMessage

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-21"
LABEL_NAMES = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI",
    "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]


class GwsError(RuntimeError):
    pass


def gws(resource, method, params=None, body=None, retry_token=True):
    params = dict(params or {})
    params["userId"] = "me"
    cmd = ["gws", "gmail", "users", resource, method,
           "--params", json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_ACCOUNT"] = ACCOUNT
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0 and retry_token and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(resource, method, params, body, retry_token=False)
    if proc.returncode != 0:
        raise GwsError(combined.strip()[:500])
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise GwsError(f"non-JSON response: {combined[:300]}") from exc


def list_all(resource, query=None):
    key = resource
    items = []
    token = None
    while True:
        params = {"maxResults": 100}
        if query is not None:
            params["q"] = query
        if token:
            params["pageToken"] = token
        page = gws(resource, "list", params)
        items.extend(page.get(key, []))
        token = page.get("nextPageToken")
        if not token:
            return items


def get_message(message_id, fmt="full"):
    return gws("messages", "get", {"id": message_id, "format": fmt})


def get_thread(thread_id):
    return gws("threads", "get", {"id": thread_id, "format": "full"})


def hdr(message, name):
    for item in (message.get("payload", {}).get("headers") or []):
        if item.get("name", "").lower() == name.lower():
            return item.get("value", "")
    return ""


def decode64(data):
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * ((4 - len(data) % 4) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


def body_parts(part):
    out = []
    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if mime in ("text/plain", "text/html") and data:
        value = decode64(data)
        if mime == "text/html":
            value = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", value, flags=re.I | re.S)
            value = re.sub(r"<br\\s*/?>", "\n", value, flags=re.I)
            value = re.sub(r"<[^>]+>", " ", value)
            value = html.unescape(value)
        out.append(value)
    for child in part.get("parts") or []:
        out.extend(body_parts(child))
    return out


def text_of(message):
    return re.sub(r"\s+", " ", "\n".join(body_parts(message.get("payload") or {}))).strip()


def ensure_labels():
    labels = gws("labels", "list").get("labels", [])
    by_name = {label.get("name"): label for label in labels}
    for name in LABEL_NAMES:
        if name not in by_name:
            gws("labels", "create", body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            })
    labels = gws("labels", "list").get("labels", [])
    by_name = {label.get("name"): label for label in labels}
    return {name: by_name[name]["id"] for name in LABEL_NAMES}


def batch_modify(ids, add=None, remove=None):
    add = list(add or [])
    remove = list(remove or [])
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        if not chunk:
            continue
        payload = {"ids": chunk}
        if add:
            payload["addLabelIds"] = add
        if remove:
            payload["removeLabelIds"] = remove
        gws("messages", "batchModify", body=payload, retry_token=False)


def snapshot():
    label_map = ensure_labels()
    promos = list_all("messages", "in:inbox category:promotions is:unread older_than:3d")
    promo_rows = []
    for item in promos:
        msg = get_message(item["id"])
        promo_rows.append({
            "id": msg["id"], "threadId": msg.get("threadId", ""),
            "from": hdr(msg, "From"), "subject": hdr(msg, "Subject"),
            "snippet": msg.get("snippet", ""),
        })
    unread = list_all("messages", "is:unread in:inbox")
    rows = []
    for item in unread:
        msg = get_message(item["id"])
        rows.append({
            "id": msg["id"], "threadId": msg.get("threadId", ""),
            "from": hdr(msg, "From"), "to": hdr(msg, "To"),
            "subject": hdr(msg, "Subject"), "date": hdr(msg, "Date"),
            "labels": msg.get("labelIds", []), "snippet": msg.get("snippet", ""),
            "bodyLead": text_of(msg)[:500],
        })
    print(json.dumps({"labels": label_map, "promotions": promo_rows, "unread": rows}, ensure_ascii=False))


def classify_message(message):
    known = {
        "19f837f880bba79f": "Financial",
        "19f837f86c784b93": "Financial",
        "19f81d4a689e0a65": "Newsletters",
        "19f81c11e715f898": "Newsletters",
        "19f81c0d36c0254a": "Newsletters",
        "19f81c0be0ea79a9": "Newsletters",
        "19f80bf4fe4bd8d6": "Action",
        "19f800a3994e9337": "Newsletters",
        "19f7fd640a523df1": "Newsletters",
        "19f7faae11df8dfe": "Newsletters",
        "19f7f81486af9a96": "Social",
        "19f7f43c74e9cb39": "Shopping",
        "19f7cd59a0de84d3": "FYI",
        "19f7c71b06d04b98": "FYI",
    }
    if message.get("id") in known:
        return known[message["id"]]
    sender = hdr(message, "From").lower()
    subject = hdr(message, "Subject").lower()
    content = " ".join((subject, sender, message.get("snippet", ""), text_of(message)[:3000])).lower()
    if any(term in content for term in ("order confirmation", "your order", "shipped", "delivery", "delivered", "tracking", "package", "purchase receipt")):
        return "Shopping"
    if any(term in content for term in ("statement", "payment received", "deposit", "contribution received", "bank notice", "transaction confirmation", "invoice", "bill is ready")):
        return "Financial"
    if any(term in content for term in ("calendar invitation", "invited you", "event update", "linkedin notification", "facebook", "instagram")):
        return "Social"
    if any(term in content for term in ("newsletter", "unsubscribe", "job alert", "digest", "google alert", "sale", "promotion", "marketing")):
        return "Newsletters"
    automated = bool(re.search(r"no-?reply|noreply|donotreply|notification|alerts?|updates?@|info@", sender))
    if not automated and re.search(r"\?|\bplease\b|\bcan you\b|\bcould you\b|\brsvp\b|\blet me know\b", content):
        return "Action"
    return "Newsletters" if automated else "FYI"


def obvious_spam(message):
    sender = hdr(message, "From").lower()
    subject = hdr(message, "Subject").lower()
    content = " ".join((subject, sender, message.get("snippet", ""), text_of(message)[:2000])).lower()
    protected = (
        "receipt", "order", "shipping", "delivery", "statement", "payment", "invoice",
        "account", "security", "password", "appointment", "travel", "reservation",
        "medical", "legal", "bank", "subscription", "renewal", "job alert",
    )
    if any(term in content for term in protected):
        return False
    solicitation = any(term in content for term in (
        "limited time", "last chance", "clearance", "shop now", "flash sale",
        "% off", "exclusive offer", "promo code", "new arrivals",
    ))
    bulk = "unsubscribe" in content or "marketing" in sender or "promotions" in sender
    return solicitation and bulk


def execute():
    result = {
        "schemaVersion": 1, "status": "ok", "date": TODAY,
        "processed": 0, "markedRead": 0, "leftUnread": 0,
        "draftsCreated": 0, "draftsExisting": 0,
        "archived": 0, "trashed": 0, "unreadAfter": [],
        "attention": [], "errors": [],
    }
    errors = result["errors"]
    try:
        label_map = ensure_labels()
    except Exception as exc:
        errors.append(f"labels: {str(exc)[:180]}")
        result["status"] = "partial"
        result["unreadAfter"] = [item["id"] for item in list_all("messages", "is:unread in:inbox")]
        result["leftUnread"] = len(result["unreadAfter"])
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return

    # Fully snapshot promotions before any trash mutation.
    try:
        promo_ids = [item["id"] for item in list_all("messages", "in:inbox category:promotions is:unread older_than:3d")]
    except Exception as exc:
        promo_ids = []
        errors.append(f"spam-list: {str(exc)[:180]}")
    for message_id in promo_ids:
        try:
            message = get_message(message_id)
            if obvious_spam(message):
                gws("messages", "trash", {"id": message_id}, retry_token=False)
                result["trashed"] += 1
        except Exception as exc:
            errors.append(f"spam {message_id}: {str(exc)[:150]}")

    try:
        unread_ids = [item["id"] for item in list_all("messages", "is:unread in:inbox")]
    except Exception as exc:
        unread_ids = []
        errors.append(f"unread-list: {str(exc)[:180]}")

    # Snapshot all draft thread IDs before considering any new draft.
    try:
        draft_items = list_all("drafts")
        draft_threads = {
            (item.get("message") or {}).get("threadId")
            for item in draft_items if (item.get("message") or {}).get("threadId")
        }
    except Exception as exc:
        draft_threads = set()
        errors.append(f"draft-list: {str(exc)[:180]}")

    fetched = {}
    classes = {}
    read_candidates = []
    stale_star = []
    attention_ids = set()
    for message_id in unread_ids:
        try:
            message = get_message(message_id)
            fetched[message_id] = message
            result["processed"] += 1
            primary = classify_message(message)
            classes[message_id] = primary
            labels = set(message.get("labelIds") or [])
            if label_map["OpenClaw/Urgent"] in labels and primary != "Urgent" and "STARRED" in labels:
                stale_star.append(message_id)

            draft_status = "none"
            reason = ""
            deadline = ""
            needs_attention = primary in ("Urgent", "Action")
            if message_id == "19f80bf4fe4bd8d6":
                needs_attention = True
                reason = "Check the important message in Julia's TreasuryDirect Investor InBox."
            elif primary == "Action":
                # Unknown Action messages are conservatively left for Julia. A reply draft is
                # created only after a specific thread inspection and confident reply wording.
                if message.get("threadId") in draft_threads:
                    draft_status = "existing"
                    result["draftsExisting"] += 1
                reason = "Julia needs to review and complete the requested action."
            elif primary == "Urgent":
                reason = "Time-sensitive message requiring Julia's review."

            if needs_attention:
                attention_ids.add(message_id)
                result["attention"].append({
                    "messageId": message_id,
                    "threadId": message.get("threadId", ""),
                    "from": hdr(message, "From"),
                    "subject": hdr(message, "Subject"),
                    "reason": reason,
                    "deadline": deadline,
                    "draftStatus": draft_status,
                })
            else:
                read_candidates.append(message_id)
        except Exception as exc:
            result["processed"] += 1
            attention_ids.add(message_id)
            errors.append(f"process {message_id}: {str(exc)[:150]}")

    # Apply one exact primary label to each successfully fetched message.
    successfully_labeled = set()
    primary_ids = set(label_map.values())
    for primary in ("Urgent", "Action", "FYI", "Financial", "Shopping", "Newsletters", "Social"):
        ids = [message_id for message_id, value in classes.items() if value == primary]
        if not ids:
            continue
        selected = label_map[f"OpenClaw/{primary}"]
        try:
            batch_modify(ids, add=[selected], remove=sorted(primary_ids - {selected}))
            successfully_labeled.update(ids)
        except Exception as exc:
            errors.append(f"label {primary}: {str(exc)[:170]}")

    urgent_ids = [message_id for message_id, value in classes.items() if value == "Urgent" and message_id in successfully_labeled]
    if urgent_ids:
        try:
            batch_modify(urgent_ids, add=["STARRED"])
        except Exception as exc:
            errors.append(f"star urgent: {str(exc)[:170]}")
    if stale_star:
        try:
            batch_modify([message_id for message_id in stale_star if message_id in successfully_labeled], remove=["STARRED"])
        except Exception as exc:
            errors.append(f"unstar stale urgent: {str(exc)[:160]}")

    read_ids = [message_id for message_id in read_candidates if message_id in successfully_labeled]
    if read_ids:
        try:
            batch_modify(read_ids, remove=["UNREAD"])
            result["markedRead"] = len(read_ids)
        except Exception as exc:
            errors.append(f"mark-read: {str(exc)[:180]}")

    # Messages with failed classification/label/read processing remain unread.
    result["leftUnread"] = len(unread_ids) - result["markedRead"]

    # Fully snapshot each routine label query, then archive only safe, read messages.
    archived_ids = set()
    for label_name in (
        "OpenClaw/FYI", "OpenClaw/Financial", "OpenClaw/Shopping",
        "OpenClaw/Newsletters", "OpenClaw/Social",
    ):
        try:
            ids = [item["id"] for item in list_all("messages", f'is:read in:inbox label:"{label_name}"')]
        except Exception as exc:
            errors.append(f"archive-list {label_name}: {str(exc)[:150]}")
            continue
        eligible = []
        for message_id in ids:
            if message_id in archived_ids:
                continue
            try:
                message = get_message(message_id)
                labels = set(message.get("labelIds") or [])
                if "UNREAD" in labels or "STARRED" in labels:
                    continue
                if label_map["OpenClaw/Urgent"] in labels or label_map["OpenClaw/Action"] in labels:
                    continue
                eligible.append(message_id)
            except Exception as exc:
                errors.append(f"archive-check {message_id}: {str(exc)[:140]}")
        if eligible:
            try:
                batch_modify(eligible, remove=["INBOX"])
                archived_ids.update(eligible)
            except Exception as exc:
                errors.append(f"archive {label_name}: {str(exc)[:160]}")
    result["archived"] = len(archived_ids)

    try:
        result["unreadAfter"] = [item["id"] for item in list_all("messages", "is:unread in:inbox")]
    except Exception as exc:
        errors.append(f"final-unread: {str(exc)[:180]}")
    if errors:
        result["status"] = "partial"
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "snapshot":
        snapshot()
    elif len(sys.argv) == 2 and sys.argv[1] == "execute":
        execute()
    else:
        raise SystemExit("usage: julia_triage_20260721.py snapshot|execute")
