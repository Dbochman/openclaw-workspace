#!/usr/bin/env python3
import base64
import email.utils
import html
import json
import os
import re
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-24"
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
    "19f9398a175c3ff9": "Financial",
    "19f92a737ba4ecf8": "Social",
    "19f9226645d68426": "Newsletters",
    "19f91484a426741e": "Urgent",
    "19f913b02010c93b": "Newsletters",
    "19f9098d9d3395a7": "Shopping",
    "19f9083b94829e17": "Newsletters",
    "19f905a0cac41ac0": "Newsletters",
    "19f8ff8c427fe689": "Newsletters",
    "19f8f22276e3966d": "Newsletters",
    "19f8f1854db55135": "Financial",
    "19f8f0f5a09946db": "Newsletters",
    "19f8edb5edb58164": "Newsletters",
    "19f8ed5529877344": "Shopping",
}


class GwsError(RuntimeError):
    pass


def gws(resource, method, params=None, body=None, allow_token_retry=True):
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
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0 and allow_token_retry and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(resource, method, params, body, allow_token_retry=False)
    if proc.returncode != 0:
        raise GwsError(combined[:500] or "gws command failed")
    if not (proc.stdout or "").strip():
        return {}
    try:
        data = json.loads(proc.stdout)
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
    for item in (message.get("payload", {}).get("headers") or []):
        if item.get("name", "").lower() == name.lower():
            return item.get("value", "")
    return ""


def decode64(value):
    if not value:
        return ""
    try:
        padded = value + "=" * ((4 - len(value) % 4) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except Exception:
        return ""


def body_text(part):
    text = []
    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        value = decode64(data)
        if mime == "text/html":
            value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
            value = re.sub(r"<[^>]+>", " ", value)
            value = html.unescape(value)
        text.append(value)
    for child in part.get("parts") or []:
        text.extend(body_text(child))
    return text


def message_text(message):
    return re.sub(r"\s+", " ", " ".join(body_text(message.get("payload") or {}))).strip()


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
                allow_token_retry=False,
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
        gws("messages", "batchModify", body=payload, allow_token_retry=False)


def obvious_spam(message):
    content = " ".join(
        [
            header(message, "From"),
            header(message, "Subject"),
            message.get("snippet", ""),
            message_text(message)[:2500],
        ]
    ).lower()
    protected = (
        "receipt", "order", "shipping", "delivery", "statement", "payment",
        "invoice", "account", "security", "password", "appointment", "travel",
        "reservation", "medical", "legal", "bank", "subscription", "renewal",
        "job alert",
    )
    if any(term in content for term in protected):
        return False
    solicitation = any(
        term in content
        for term in (
            "limited time", "last chance", "clearance", "shop now",
            "flash sale", "% off", "exclusive offer", "promo code",
            "new arrivals",
        )
    )
    return solicitation and "unsubscribe" in content


def make_result():
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


def run():
    result = make_result()
    errors = result["errors"]
    try:
        label_map = ensure_labels()
    except Exception as exc:
        result["status"] = "partial"
        errors.append(f"labels: {str(exc)[:160]}")
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return

    try:
        promotion_ids = [
            item["id"]
            for item in list_all(
                "messages",
                "in:inbox category:promotions is:unread older_than:3d",
            )
        ]
    except Exception as exc:
        promotion_ids = []
        errors.append(f"spam-list: {str(exc)[:160]}")
    for message_id in promotion_ids:
        try:
            message = get_message(message_id)
            if obvious_spam(message):
                gws(
                    "messages",
                    "trash",
                    {"id": message_id},
                    allow_token_retry=False,
                )
                result["trashed"] += 1
        except Exception as exc:
            errors.append(f"spam {message_id}: {str(exc)[:130]}")

    try:
        unread_ids = [
            item["id"]
            for item in list_all("messages", "is:unread in:inbox")
        ]
    except Exception as exc:
        unread_ids = []
        errors.append(f"unread-list: {str(exc)[:160]}")

    fetched = {}
    classes = {}
    previous_labels = {}
    processing_failures = set()
    for message_id in unread_ids:
        try:
            message = get_message(message_id)
            fetched[message_id] = message
            previous_labels[message_id] = set(message.get("labelIds") or [])
            result["processed"] += 1
            if message_id not in CLASSIFICATIONS:
                raise ValueError("message arrived after the reviewed snapshot")
            classes[message_id] = CLASSIFICATIONS[message_id]
        except Exception as exc:
            processing_failures.add(message_id)
            errors.append(f"process {message_id}: {str(exc)[:130]}")

    all_primary_ids = set(label_map.values())
    labeled = set()
    for primary in (
        "Urgent", "Action", "FYI", "Financial",
        "Shopping", "Newsletters", "Social",
    ):
        ids = [mid for mid, value in classes.items() if value == primary]
        if not ids:
            continue
        selected = label_map[f"OpenClaw/{primary}"]
        groups = {}
        for message_id in ids:
            remove = set(all_primary_ids - {selected})
            if (
                label_map["OpenClaw/Urgent"] in previous_labels[message_id]
                and primary != "Urgent"
                and "STARRED" in previous_labels[message_id]
            ):
                remove.add("STARRED")
            add = {selected}
            if primary == "Urgent":
                add.add("STARRED")
            key = (tuple(sorted(add)), tuple(sorted(remove)))
            groups.setdefault(key, []).append(message_id)
        for (add, remove), group_ids in groups.items():
            try:
                batch_modify(group_ids, add=add, remove=remove)
                labeled.update(group_ids)
            except Exception as exc:
                processing_failures.update(group_ids)
                errors.append(f"label {primary}: {str(exc)[:150]}")

    attention_ids = set()
    urgent_ids = [
        mid for mid, value in classes.items()
        if value == "Urgent" and mid in labeled
    ]
    for message_id in urgent_ids:
        message = fetched[message_id]
        attention_ids.add(message_id)
        result["attention"].append(
            {
                "messageId": message_id,
                "threadId": message.get("threadId", ""),
                "from": header(message, "From"),
                "subject": header(message, "Subject"),
                "reason": "Unexpected financial-account access suspension requires Julia's review.",
                "deadline": "",
                "draftStatus": "none",
            }
        )

    action_ids = [
        mid for mid, value in classes.items()
        if value == "Action" and mid in labeled
    ]
    if action_ids:
        try:
            drafts = list_all("drafts")
            draft_threads = {
                (item.get("message") or {}).get("threadId")
                for item in drafts
                if (item.get("message") or {}).get("threadId")
            }
        except Exception as exc:
            draft_threads = set()
            processing_failures.update(action_ids)
            errors.append(f"draft-list: {str(exc)[:150]}")
        for message_id in action_ids:
            if message_id in processing_failures:
                continue
            message = fetched[message_id]
            status = (
                "existing"
                if message.get("threadId") in draft_threads
                else "none"
            )
            if status == "existing":
                result["draftsExisting"] += 1
            attention_ids.add(message_id)
            result["attention"].append(
                {
                    "messageId": message_id,
                    "threadId": message.get("threadId", ""),
                    "from": header(message, "From"),
                    "subject": header(message, "Subject"),
                    "reason": "Julia needs to review and complete the requested action.",
                    "deadline": "",
                    "draftStatus": status,
                }
            )

    keep_unread = attention_ids | processing_failures
    read_ids = [
        mid
        for mid in unread_ids
        if mid in labeled and mid not in keep_unread
    ]
    if read_ids:
        try:
            batch_modify(read_ids, remove=["UNREAD"])
            result["markedRead"] = len(read_ids)
        except Exception as exc:
            processing_failures.update(read_ids)
            keep_unread.update(read_ids)
            errors.append(f"mark-read: {str(exc)[:150]}")
    result["leftUnread"] = len(
        [mid for mid in unread_ids if mid not in read_ids or mid in keep_unread]
    )

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
                item["id"]
                for item in list_all(
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
            item["id"]
            for item in list_all("messages", "is:unread in:inbox")
        ]
    except Exception as exc:
        errors.append(f"final-unread: {str(exc)[:150]}")
    if errors:
        result["status"] = "partial"
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    run()
