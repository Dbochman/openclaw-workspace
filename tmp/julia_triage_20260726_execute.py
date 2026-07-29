#!/usr/bin/env python3
import base64
import html
import json
import os
import re
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-26"
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
    "19f9bbb69086526c": "FYI",
    "19f9bbb688acaa30": "FYI",
    "19f9b9db6e359e61": "Shopping",
    "19f99c6f1bbec01e": "Financial",
    "19f995be5bd6c3fa": "Newsletters",
    "19f9902198f92998": "Newsletters",
    "19f95ff8b0ec5724": "FYI",
    "19f95ff88d5d5e62": "FYI",
    "19f91484a426741e": "Urgent",
}


class GwsError(RuntimeError):
    pass


def gws(resource, method, params=None, body=None, retry_token=True):
    params = dict(params or {})
    params["userId"] = "me"
    cmd = [
        "gws", "gmail", "users", resource, method,
        "--params", json.dumps(params, separators=(",", ":")),
    ]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_ACCOUNT"] = ACCOUNT
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode and retry_token and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(resource, method, params, body, retry_token=False)
    if proc.returncode:
        raise GwsError(combined.strip()[:500] or "gws command failed")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise GwsError("Gmail returned invalid JSON") from exc
    if isinstance(data, dict) and data.get("error"):
        raise GwsError(json.dumps(data["error"], separators=(",", ":"))[:500])
    return data


def list_all(resource, query=None):
    items = []
    page_token = None
    while True:
        params = {"maxResults": 100}
        if query is not None:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        page = gws(resource, "list", params)
        items.extend(page.get(resource, []) or [])
        page_token = page.get("nextPageToken")
        if not page_token:
            return items


def get_message(message_id):
    return gws("messages", "get", {"id": message_id, "format": "full"})


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


def message_text(message):
    return re.sub(r"\s+", " ", " ".join(decode_part(message.get("payload") or {}))).strip()


def ensure_labels():
    labels = gws("labels", "list").get("labels", []) or []
    by_name = {item.get("name"): item for item in labels}
    for name in LABEL_NAMES:
        if name not in by_name:
            gws(
                "labels",
                "create",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
                retry_token=False,
            )
    labels = gws("labels", "list").get("labels", []) or []
    by_name = {item.get("name"): item for item in labels}
    return {name: by_name[name]["id"] for name in LABEL_NAMES}


def batch_modify(ids, add=None, remove=None):
    for offset in range(0, len(ids), 1000):
        chunk = ids[offset:offset + 1000]
        if not chunk:
            continue
        payload = {"ids": chunk}
        if add:
            payload["addLabelIds"] = list(add)
        if remove:
            payload["removeLabelIds"] = list(remove)
        gws("messages", "batchModify", body=payload, retry_token=False)


def obvious_spam(message):
    content = " ".join([
        header(message, "From"),
        header(message, "Subject"),
        message.get("snippet", ""),
        message_text(message)[:2500],
    ]).lower()
    protected = (
        "receipt", "order", "shipping", "delivery", "statement", "payment",
        "invoice", "account", "security", "password", "appointment", "travel",
        "reservation", "medical", "legal", "bank", "subscription", "renewal",
        "job alert",
    )
    if any(term in content for term in protected):
        return False
    solicitation = any(term in content for term in (
        "limited time", "last chance", "clearance", "shop now", "flash sale",
        "% off", "exclusive offer", "promo code", "new arrivals",
    ))
    return solicitation and "unsubscribe" in content


def result_template():
    return {
        "schemaVersion": 1,
        "status": "ok",
        "date": TODAY,
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
    result = result_template()
    errors = result["errors"]
    try:
        label_map = ensure_labels()
    except Exception as exc:
        errors.append(f"labels: {str(exc)[:160]}")
        result["status"] = "partial"
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return

    try:
        promo_ids = [
            item["id"] for item in list_all(
                "messages",
                "in:inbox category:promotions is:unread older_than:3d",
            )
        ]
    except Exception as exc:
        promo_ids = []
        errors.append(f"spam-list: {str(exc)[:160]}")
    for message_id in promo_ids:
        try:
            message = get_message(message_id)
            if obvious_spam(message):
                gws("messages", "trash", {"id": message_id}, retry_token=False)
                result["trashed"] += 1
        except Exception as exc:
            errors.append(f"spam {message_id}: {str(exc)[:130]}")

    try:
        unread_ids = [
            item["id"] for item in list_all("messages", "is:unread in:inbox")
        ]
    except Exception as exc:
        unread_ids = []
        errors.append(f"unread-list: {str(exc)[:160]}")

    try:
        draft_items = list_all("drafts")
        draft_threads = {
            (item.get("message") or {}).get("threadId")
            for item in draft_items
            if (item.get("message") or {}).get("threadId")
        }
    except Exception as exc:
        draft_threads = set()
        errors.append(f"draft-list: {str(exc)[:160]}")

    fetched = {}
    classes = {}
    prior_labels = {}
    failures = set()
    for message_id in unread_ids:
        result["processed"] += 1
        try:
            message = get_message(message_id)
            fetched[message_id] = message
            prior_labels[message_id] = set(message.get("labelIds") or [])
            if message_id not in CLASSIFICATIONS:
                raise ValueError("message arrived after reviewed snapshot")
            classes[message_id] = CLASSIFICATIONS[message_id]
        except Exception as exc:
            failures.add(message_id)
            errors.append(f"process {message_id}: {str(exc)[:130]}")

    all_primary_ids = set(label_map.values())
    labeled = set()
    for primary in (
        "Urgent", "Action", "FYI", "Financial",
        "Shopping", "Newsletters", "Social",
    ):
        ids = [message_id for message_id, value in classes.items() if value == primary]
        if not ids:
            continue
        selected = label_map[f"OpenClaw/{primary}"]
        groups = {}
        for message_id in ids:
            remove = set(all_primary_ids - {selected})
            if (
                label_map["OpenClaw/Urgent"] in prior_labels[message_id]
                and primary != "Urgent"
                and "STARRED" in prior_labels[message_id]
            ):
                remove.add("STARRED")
            add = {selected}
            if primary == "Urgent":
                add.add("STARRED")
            groups.setdefault((tuple(sorted(add)), tuple(sorted(remove))), []).append(message_id)
        for (add, remove), group_ids in groups.items():
            try:
                batch_modify(group_ids, add=add, remove=remove)
                labeled.update(group_ids)
            except Exception as exc:
                failures.update(group_ids)
                errors.append(f"label {primary}: {str(exc)[:150]}")

    attention_ids = set()
    urgent_id = "19f91484a426741e"
    if urgent_id in labeled:
        message = fetched[urgent_id]
        attention_ids.add(urgent_id)
        result["attention"].append({
            "messageId": urgent_id,
            "threadId": message.get("threadId", ""),
            "from": header(message, "From"),
            "subject": header(message, "Subject"),
            "reason": "T. Rowe Price reports that account access was suspended and requires Julia's review.",
            "deadline": "",
            "draftStatus": "none",
        })

    for message_id, primary in classes.items():
        if primary != "Action" or message_id not in labeled:
            continue
        message = fetched[message_id]
        status = "existing" if message.get("threadId") in draft_threads else "none"
        if status == "existing":
            result["draftsExisting"] += 1
        attention_ids.add(message_id)
        result["attention"].append({
            "messageId": message_id,
            "threadId": message.get("threadId", ""),
            "from": header(message, "From"),
            "subject": header(message, "Subject"),
            "reason": "Julia needs to review and complete the requested action.",
            "deadline": "",
            "draftStatus": status,
        })

    read_ids = [
        message_id for message_id in unread_ids
        if message_id in labeled
        and message_id not in failures
        and message_id not in attention_ids
    ]
    if read_ids:
        try:
            batch_modify(read_ids, remove=["UNREAD"])
            result["markedRead"] = len(read_ids)
        except Exception as exc:
            failures.update(read_ids)
            errors.append(f"mark-read: {str(exc)[:160]}")

    archived_ids = set()
    for label_name in (
        "OpenClaw/FYI",
        "OpenClaw/Financial",
        "OpenClaw/Shopping",
        "OpenClaw/Newsletters",
        "OpenClaw/Social",
    ):
        try:
            candidate_ids = [
                item["id"] for item in list_all(
                    "messages",
                    f'is:read in:inbox label:"{label_name}"',
                )
            ]
        except Exception as exc:
            errors.append(f"archive-list {label_name}: {str(exc)[:130]}")
            continue
        eligible = []
        for message_id in candidate_ids:
            if message_id in archived_ids:
                continue
            try:
                message = get_message(message_id)
                labels = set(message.get("labelIds") or [])
                if (
                    "UNREAD" in labels
                    or "STARRED" in labels
                    or label_map["OpenClaw/Urgent"] in labels
                    or label_map["OpenClaw/Action"] in labels
                ):
                    continue
                eligible.append(message_id)
            except Exception as exc:
                errors.append(f"archive-check {message_id}: {str(exc)[:120]}")
        if eligible:
            try:
                batch_modify(eligible, remove=["INBOX"])
                archived_ids.update(eligible)
            except Exception as exc:
                errors.append(f"archive {label_name}: {str(exc)[:140]}")
    result["archived"] = len(archived_ids)

    try:
        result["unreadAfter"] = [
            item["id"] for item in list_all("messages", "is:unread in:inbox")
        ]
        result["leftUnread"] = len(result["unreadAfter"])
    except Exception as exc:
        errors.append(f"final-unread: {str(exc)[:150]}")
    if errors:
        result["status"] = "partial"
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
