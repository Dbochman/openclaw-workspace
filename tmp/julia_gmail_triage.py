#!/usr/bin/env python3
import argparse, base64, datetime as dt, email.utils, html, json, os, re, subprocess, sys, time
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from email.headerregistry import Address

ACCOUNT = "julia.joy.jennings@gmail.com"
ALIASES = {ACCOUNT.lower(), "juliajoyjennings@gmail.com", "julia.joy.jennings@googlemail.com", "juliajoyjennings@googlemail.com"}
PRIMARY_NAMES = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI", "OpenClaw/Financial",
    "OpenClaw/Shopping", "OpenClaw/Newsletters", "OpenClaw/Social"
]
LABEL_KEY = {
    "Urgent": "OpenClaw/Urgent", "Action": "OpenClaw/Action", "FYI": "OpenClaw/FYI",
    "Financial": "OpenClaw/Financial", "Shopping": "OpenClaw/Shopping",
    "Newsletters": "OpenClaw/Newsletters", "Social": "OpenClaw/Social",
}
ERRS=[]

FIN_RE = re.compile(r"\b(bank|credit card|statement|invoice|bill|billing|payment|paid|deposit|withdrawal|transaction|venmo|paypal|zelle|stripe|square|mortgage|loan|tax|irs|treasury\s*direct|treasurydirect|insurance|claim|premium|autopay|balance|account ending|financial|investment|fidelity|vanguard|schwab|chase|amex|american express|capital one|citi|bank of america|boa|sofi|etrade|etrade|utility|electric|gas bill|water bill|tuition|payroll|direct deposit|coinbase)\b", re.I)
SHOP_RE = re.compile(r"\b(order|ordered|order #|receipt|shipped|shipping|delivered|delivery|out for delivery|tracking|package|purchase|return|refund|refill|amazon|etsy|shopify|target|walmart|instacart|doordash|ubereats|uber eats|grubhub|fedex|ups|usps|petco)\b", re.I)
SHOP_EVENT_RE = re.compile(r"\b(order|ordered|order #|receipt|shipped|shipping|delivered|delivery|out for delivery|tracking|package|purchase|return|refund|refill)\b", re.I)
FIN_SOURCE_RE = re.compile(r"\b(venmo|paypal|stripe|square|coinbase|treasury|fiscal\.treasury|bank|chase|amex|americanexpress|capitalone|citi|fidelity|vanguard|schwab|sofi|invoice|billing|payment)\b", re.I)
AUTOMATION_LOCAL_RE = re.compile(r"\b(no[-_]?reply|noreply|donotreply|do-not-reply|notification|notifications|alert|alerts|updates|email|mailer|newsletter|orders|order|shipping|support|info|hello|marketing|feedback|customerexperience|upcoming-invoice|venmo)\b", re.I)
SOCIAL_RE = re.compile(r"\b(invitation|invited|accepted:|calendar|event|facebook|instagram|linkedin|nextdoor|meetup|evite|eventbrite|rsvp|party|lunch|zoom|teams meeting|google meet)\b", re.I)
NEWS_RE = re.compile(r"\b(newsletter|digest|roundup|google alert|job alert|unsubscribe|subscription|survey|sale|discount|deal|offer|promo|promotion|marketing|limited time|% off|save \d+|new arrivals|shop now|webinar|course|tips|update from|weekly|daily brief|sponsored)\b", re.I)
URGENT_RE = re.compile(r"\b(urgent|today|by today|tonight|tomorrow|deadline|overdue|past due|failed payment|payment failed|declined|suspicious|fraud|unauthorized|security alert|account locked|verify now|immediate action|required immediately|shut off|final notice|cancellation|cancelled|canceled|appointment today)\b", re.I)
CRITICAL_RE = re.compile(r"\b(failed payment|payment failed|declined|suspicious|fraud|unauthorized|security alert|account locked|verify now|overdue|past due|final notice|shut off|immediate action|required immediately)\b", re.I)
ACTION_RE = re.compile(r"\b(can you|could you|would you|please|let me know|reply|respond|confirm|choose|schedule|send me|sign|complete|fill out|register|rsvp|question|\?|are you available|availability|follow up|need you to|waiting for|thoughts\?)\b", re.I)
MEDLEGAL_RE = re.compile(r"\b(doctor|medical|health|clinic|hospital|prescription|lab result|lawyer|attorney|legal|court|lease|contract|settlement|insurance claim)\b", re.I)
SAFE_NOT_TRASH_RE = re.compile(r"\b(receipt|order|shipping|delivered|account|security|password|statement|bill|invoice|payment|bank|doctor|medical|appointment|travel|flight|hotel|reservation|ticket|legal|tax|insurance|school|teacher|personal)\b", re.I)
SPAMMY_RE = re.compile(r"\b(sale|discount|deal|promo|promotion|limited time|last chance|ends tonight|% off|save \d+|coupon|clearance|black friday|cyber|shop now|free shipping|giveaway|sweepstakes|new arrivals|exclusive offer|today only)\b", re.I)
NOREPLY_RE = re.compile(r"\b(no[-_ ]?reply|noreply|donotreply|do-not-reply|notifications?|automated|mailer|newsletter|support|hello@|info@|marketing|alerts?)\b", re.I)

def now_date():
    return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def run_gws(parts, params=None, body=None, retries=1):
    # parts begin after: gws gmail users
    cmd = ["gws", "gmail", "users"] + parts
    if params is None:
        params = {"userId":"me"}
    elif "userId" not in params:
        params = {"userId":"me", **params}
    cmd += ["--params", json.dumps(params, separators=(",",":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",",":"))]
    cmd += ["--account", ACCOUNT]
    env = os.environ.copy(); env["GOOGLE_WORKSPACE_CLI_ACCOUNT"] = ACCOUNT
    last = None
    for attempt in range(retries+1):
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out = (p.stdout or "").strip(); err = (p.stderr or "").strip(); last=(p.returncode,out,err)
        if p.returncode == 0:
            if not out:
                return {}
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                # Some paginated commands may emit NDJSON; not used here, but keep robust.
                lines=[json.loads(x) for x in out.splitlines() if x.strip()]
                if len(lines)==1: return lines[0]
                return {"pages": lines}
        joined = out + "\n" + err
        if attempt < retries and ("Failed to get token" in joined or "auth failed" in joined or "rateLimit" in joined):
            time.sleep(5)
            continue
        raise RuntimeError((err or out or f"gws failed rc={p.returncode}")[:500])
    raise RuntimeError(str(last)[:500])

def list_all_messages(q):
    ids=[]; token=None
    while True:
        params={"userId":"me","q":q,"maxResults":100}
        if token: params["pageToken"]=token
        data=run_gws(["messages","list"], params=params)
        for m in data.get("messages",[]) or []:
            ids.append({"id":m["id"], "threadId":m.get("threadId")})
        token=data.get("nextPageToken")
        if not token: break
    return ids

def list_all_drafts():
    drafts=[]; token=None
    while True:
        params={"userId":"me","maxResults":100}
        if token: params["pageToken"]=token
        data=run_gws(["drafts","list"], params=params)
        for d in data.get("drafts",[]) or []:
            drafts.append(d)
        token=data.get("nextPageToken")
        if not token: break
    return drafts

def get_msg(mid):
    return run_gws(["messages","get"], params={"userId":"me","id":mid,"format":"full"})

def get_thread(tid):
    return run_gws(["threads","get"], params={"userId":"me","id":tid,"format":"full"})

def batch_modify(ids, add=None, remove=None):
    add=add or []; remove=remove or []
    if not ids: return
    for i in range(0, len(ids), 1000):
        body={"ids":ids[i:i+1000]}
        if add: body["addLabelIds"]=add
        if remove: body["removeLabelIds"]=remove
        run_gws(["messages","batchModify"], params={"userId":"me"}, body=body)

def trash_msg(mid):
    return run_gws(["messages","trash"], params={"userId":"me","id":mid})

def headers(msg):
    hs={}
    for h in (((msg.get("payload") or {}).get("headers")) or []):
        hs.setdefault(h.get("name","").lower(), h.get("value", ""))
    return hs

def get_header(msg, name):
    return headers(msg).get(name.lower(), "")

def parse_addr(v):
    try:
        addrs=email.utils.getaddresses([v])
        if addrs:
            name, addr = addrs[0]
            return name.strip(), addr.lower().strip()
    except Exception:
        pass
    return "", v.lower().strip()

def b64decode_url(data):
    if not data: return ""
    data += "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
    except Exception:
        return ""

def strip_html(s):
    s=re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    s=re.sub(r"(?is)<br\s*/?>", "\n", s)
    s=re.sub(r"(?is)</p>", "\n", s)
    s=re.sub(r"(?is)<.*?>", " ", s)
    s=html.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", s)

def body_text(msg):
    payload=msg.get("payload") or {}
    plains=[]; htmls=[]
    def walk(part):
        mime=(part.get("mimeType") or "").lower()
        data=((part.get("body") or {}).get("data"))
        if data:
            txt=b64decode_url(data)
            if mime.startswith("text/plain"):
                plains.append(txt)
            elif mime.startswith("text/html"):
                htmls.append(strip_html(txt))
        for p in part.get("parts") or []:
            walk(p)
    walk(payload)
    txt="\n".join(plains).strip() or "\n".join(htmls).strip()
    txt=re.sub(r"\n{3,}", "\n\n", txt)
    return txt[:12000]

def is_bulk(msg):
    hs=headers(msg)
    return bool(hs.get("list-unsubscribe") or "bulk" in hs.get("precedence","").lower() or "list" in hs.get("precedence","").lower() or hs.get("auto-submitted","").lower() not in ("", "no"))

def is_from_julia(msg):
    _, addr=parse_addr(get_header(msg,"from"))
    return addr in ALIASES

def real_person(msg):
    frm=get_header(msg,"from")
    name, addr=parse_addr(frm)
    domain=addr.split("@")[-1] if "@" in addr else ""
    local=addr.split("@",1)[0] if "@" in addr else addr
    if is_bulk(msg): return False
    if NOREPLY_RE.search(frm) or AUTOMATION_LOCAL_RE.search(local): return False
    if domain in {"gmail.com","icloud.com","me.com","mac.com","yahoo.com","outlook.com","hotmail.com","aol.com","proton.me","protonmail.com"}: return True
    if FIN_SOURCE_RE.search(frm) or re.search(r"\b(usps|walmart|noom|delta dental|linkedin|google alerts|oura|uber|petco|coinbase|stripe)\b", frm, re.I): return False
    # Custom-domain senders are treated as people only when both display name and local part look human.
    if name and re.search(r"^[a-z]+[._-][a-z]+$", local, re.I) and not re.search(r"\b(team|support|service|notifications|alerts|office|admin|sales|marketing)\b", name, re.I): return True
    return False

def msg_summary(msg):
    hs=headers(msg)
    subject=hs.get("subject","")
    frm=hs.get("from","")
    labels=msg.get("labelIds") or []
    text=(subject+"\n"+frm+"\n"+body_text(msg)[:4000])
    return subject, frm, labels, text

def classify(msg):
    subject, frm, labels, text = msg_summary(msg)
    bulk=is_bulk(msg)
    person=real_person(msg)
    # Unexpected failures/time-sensitive requests are urgent. Routine automated "today"/digest/footer language is not.
    subj_from = subject + "\n" + frm
    if (CRITICAL_RE.search(subj_from) or (CRITICAL_RE.search(text) and not bulk and FIN_SOURCE_RE.search(text)) or (person and URGENT_RE.search(text))):
        return "Urgent", "time-sensitive request or account/security/financial issue"
    if person:
        # Calendar/event acceptances from people are social notifications unless they ask for a response.
        if SOCIAL_RE.search(text) and not ACTION_RE.search(text):
            return "Social", "social/event/calendar notification"
        if MEDLEGAL_RE.search(text) and ACTION_RE.search(text):
            return "Action", "sensitive medical/legal/personal action needed"
        if ACTION_RE.search(text):
            return "Action", "direct question or reply/action requested"
        if FIN_RE.search(text):
            return "Financial", "financial/billing/account notice"
        if SHOP_RE.search(text):
            return "Shopping", "order/receipt/shipping/delivery update"
        return "FYI", "informational message from a person"
    # Automated/service mail: pick the concrete bucket, never reply-draft just because the body says "please" or contains a question.
    if FIN_RE.search(text) and FIN_SOURCE_RE.search(subj_from):
        return "Financial", "financial/billing/account notice"
    if SHOP_EVENT_RE.search(subj_from) or re.search(r"usps.*digest|informed delivery", subj_from, re.I):
        return "Shopping", "order/receipt/shipping/delivery update"
    if NEWS_RE.search(subj_from) or ("CATEGORY_PROMOTIONS" in labels and not FIN_SOURCE_RE.search(subj_from)):
        return "Newsletters", "newsletter, digest, marketing, or promotion"
    if SOCIAL_RE.search(subj_from):
        return "Social", "social/event/calendar notification"
    if FIN_RE.search(text):
        return "Financial", "financial/billing/account notice"
    if NEWS_RE.search(text) or bulk or "CATEGORY_PROMOTIONS" in labels:
        return "Newsletters", "newsletter, digest, marketing, or promotion"
    if SOCIAL_RE.search(text):
        return "Social", "social/event/calendar notification"
    return "Newsletters", "automated informational or promotional mail"

def should_trash_spam(msg):
    subject, frm, labels, text = msg_summary(msg)
    s=text[:3000]
    if SAFE_NOT_TRASH_RE.search(s): return False
    if "CATEGORY_PROMOTIONS" not in labels and not is_bulk(msg): return False
    if SPAMMY_RE.search(s): return True
    # Very obvious bulk promo even without sale words.
    return bool(is_bulk(msg) and re.search(r"\b(unsubscribe|manage preferences)\b", s, re.I) and re.search(r"\b(shop|buy|brand|collection|product|offer)\b", s, re.I))

def ensure_labels(run):
    data=run_gws(["labels","list"], params={"userId":"me"})
    labels=data.get("labels",[]) or []
    by_name={l.get("name"): l.get("id") for l in labels}
    if run:
        for name in PRIMARY_NAMES:
            if name not in by_name:
                try:
                    created=run_gws(["labels","create"], params={"userId":"me"}, body={"name":name,"labelListVisibility":"labelShow","messageListVisibility":"show"})
                    by_name[created.get("name", name)] = created.get("id")
                except Exception as e:
                    ERRS.append(f"label create {name}: {e}")
        data=run_gws(["labels","list"], params={"userId":"me"})
        by_name={l.get("name"): l.get("id") for l in data.get("labels",[]) or []}
    return {name:by_name.get(name) for name in PRIMARY_NAMES}

def make_reply_raw(src_msg, to_addr, to_name, draft_body):
    hs=headers(src_msg)
    subj=hs.get("subject", "") or "(no subject)"
    if not subj.lower().startswith("re:"):
        subj="Re: " + subj
    msg=EmailMessage()
    msg["To"] = email.utils.formataddr((to_name, to_addr)) if to_name else to_addr
    msg["From"] = ACCOUNT
    msg["Subject"] = subj
    if hs.get("message-id"):
        msg["In-Reply-To"] = hs.get("message-id")
        refs = (hs.get("references", "") + " " + hs.get("message-id")).strip()
        msg["References"] = refs
    msg.set_content(draft_body)
    raw=base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
    return raw

def create_draft(src_msg, thread_id):
    name, addr=parse_addr(get_header(src_msg,"reply-to") or get_header(src_msg,"from"))
    if not addr:
        raise RuntimeError("no reply recipient")
    # intentionally concise and review-safe; Julia will edit before sending.
    first = (name.split()[0] if name else "")
    greeting = f"Hi {first}," if first else "Hi,"
    body = f"{greeting}\n\nThanks for reaching out. I’ll take a look and get back to you soon.\n\nBest,\nJulia\n"
    raw=make_reply_raw(src_msg, addr, name, body)
    return run_gws(["drafts","create"], params={"userId":"me"}, body={"message":{"raw":raw,"threadId":thread_id}})

def thread_needs_reply(thread, source_id):
    msgs=thread.get("messages",[]) or []
    # Chronological by internalDate.
    msgs=sorted(msgs, key=lambda m:int(m.get("internalDate","0")))
    latest_non_draft=None
    for m in msgs:
        labels=set(m.get("labelIds") or [])
        if "DRAFT" not in labels:
            latest_non_draft=m
    if latest_non_draft is None:
        return False, "thread has no non-draft messages"
    if is_from_julia(latest_non_draft) or "SENT" in set(latest_non_draft.get("labelIds") or []):
        return False, "Julia already replied after the outstanding request"
    # If latest non-draft is someone else and looks actionable, reply needed.
    cls, _ = classify(latest_non_draft)
    if cls in ("Action", "Urgent"):
        return True, "latest message still appears to need Julia's response"
    return False, "thread no longer appears to require a reply"

def brief_deadline(msg):
    text=msg_summary(msg)[3]
    m=re.search(r"\b(today|tonight|tomorrow|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|by \d{1,2}/\d{1,2}|deadline[^.\n]{0,60})\b", text, re.I)
    return m.group(0)[:120] if m else ""

def attention_reason(label, draft_status, reason):
    if draft_status in ("created","existing"):
        return "Reply draft needs Julia's review"
    if label=="Urgent": return reason
    return reason

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--plan", action="store_true")
    args=ap.parse_args()
    run=args.run
    result={"schemaVersion":1,"status":"ok","date":now_date(),"processed":0,"markedRead":0,"leftUnread":0,"draftsCreated":0,"draftsExisting":0,"archived":0,"trashed":0,"unreadAfter":[],"attention":[],"errors":[]}
    # Auth check with retry is naturally included.
    try:
        run_gws(["messages","list"], params={"userId":"me","q":"is:unread in:inbox","maxResults":1}, retries=1)
    except Exception as e:
        result["status"]="auth_error"; result["errors"]=[f"auth: {e}"]
        print(json.dumps(result, separators=(",",":")))
        return
    try:
        label_map=ensure_labels(run)
        missing=[k for k,v in label_map.items() if not v]
        if missing:
            raise RuntimeError("missing OpenClaw labels: "+", ".join(missing))
        primary_ids=[label_map[n] for n in PRIMARY_NAMES]
        # 2 spam removal
        spam_ids=list_all_messages("in:inbox category:promotions is:unread older_than:3d")
        trash_ids=[]
        for item in spam_ids:
            try:
                msg=get_msg(item["id"])
                if should_trash_spam(msg):
                    trash_ids.append(item["id"])
            except Exception as e:
                ERRS.append(f"spam fetch/classify {item['id']}: {e}")
        if run:
            for mid in trash_ids:
                try:
                    trash_msg(mid)
                    result["trashed"]+=1
                except Exception as e:
                    ERRS.append(f"trash {mid}: {e}")
        else:
            result["trashed"]=len(trash_ids)
        # 3 complete unread inbox after spam
        unread=list_all_messages("is:unread in:inbox")
        snapshot=[x["id"] for x in unread]
        result["processed"]=len(snapshot)
        drafts=list_all_drafts()
        draft_threads=set(((d.get("message") or {}).get("threadId")) for d in drafts if (d.get("message") or {}).get("threadId"))
        modifications=[]  # (id, add_ids, remove_ids, mark_read_bool)
        mark_read=[]
        keep_unread=set()
        plan_rows=[]
        for item in unread:
            mid=item["id"]
            try:
                msg=get_msg(mid)
                hs=headers(msg); subj=hs.get("subject",""); frm=hs.get("from","")
                labels=set(msg.get("labelIds") or [])
                original_had_urgent=label_map["OpenClaw/Urgent"] in labels
                label, reason=classify(msg)
                draft_status="none"
                attn_reason=""
                needs_attention=False
                final_label=label
                if label=="Action":
                    try:
                        thread=get_thread(msg.get("threadId") or item.get("threadId"))
                        needs_reply, why=thread_needs_reply(thread, mid)
                        if needs_reply:
                            if (msg.get("threadId") or item.get("threadId")) in draft_threads:
                                draft_status="existing"; result["draftsExisting"]+=1
                            else:
                                if run:
                                    create_draft(msg, msg.get("threadId") or item.get("threadId"))
                                draft_status="created"; result["draftsCreated"]+=1
                            needs_attention=True; attn_reason="Reply draft needs Julia's review"
                        else:
                            # If no reply needed, downgrade unless non-reply action remains (rare heuristic).
                            if re.search(r"\b(sign|complete|fill out|register|pay|submit|upload|choose|book|schedule)\b", msg_summary(msg)[3], re.I):
                                needs_attention=True; attn_reason="Action only Julia can take"
                            else:
                                final_label="FYI"; reason=why
                    except Exception as e:
                        ERRS.append(f"thread/draft {mid}: {e}")
                        needs_attention=True; attn_reason="Processing failed; Julia should review"
                elif label=="Urgent":
                    needs_attention=True; attn_reason=reason
                elif MEDLEGAL_RE.search(msg_summary(msg)[3]) and real_person(msg):
                    # Sensitive mail should be reviewed even if informational.
                    needs_attention=True; attn_reason="Sensitive personal/medical/legal content to review"
                label_id=label_map[LABEL_KEY[final_label]]
                remove_ids=[pid for pid in primary_ids if pid != label_id]
                add_ids=[label_id]
                if final_label=="Urgent": add_ids.append("STARRED")
                elif original_had_urgent and "STARRED" in labels:
                    remove_ids.append("STARRED")
                if needs_attention:
                    keep_unread.add(mid)
                    result["attention"].append({"messageId":mid,"threadId":msg.get("threadId") or item.get("threadId") or "","from":frm,"subject":subj,"reason":attention_reason(final_label,draft_status,attn_reason or reason),"deadline":brief_deadline(msg),"draftStatus":draft_status})
                else:
                    mark_read.append(mid)
                    remove_ids.append("UNREAD")
                modifications.append((mid, tuple(sorted(set(add_ids))), tuple(sorted(set(remove_ids)))))
                plan_rows.append({"id":mid,"from":frm,"subject":subj,"label":final_label,"markRead":mid in mark_read,"attention":needs_attention,"draftStatus":draft_status,"reason":reason})
            except Exception as e:
                ERRS.append(f"process {mid}: {e}")
                keep_unread.add(mid)
        result["markedRead"]=len(mark_read)
        if run:
            # Group identical label changes.
            groups={}
            for mid, add, rem in modifications:
                groups.setdefault((add,rem), []).append(mid)
            for (add,rem), ids in groups.items():
                try:
                    batch_modify(ids, add=list(add), remove=list(rem))
                except Exception as e:
                    ERRS.append(f"batchModify {len(ids)} messages: {e}")
                    # Failed group stays unread by instruction if read-state/label failed.
            # 6 archive stale read mail
            stale=list_all_messages("is:read in:inbox older_than:1d")
            archive_ids=[]
            for item in stale:
                try:
                    msg=get_msg(item["id"])
                    labs=set(msg.get("labelIds") or [])
                    if label_map["OpenClaw/Urgent"] in labs or label_map["OpenClaw/Action"] in labs or "STARRED" in labs:
                        continue
                    archive_ids.append(item["id"])
                except Exception as e:
                    ERRS.append(f"archive fetch {item['id']}: {e}")
            try:
                batch_modify(archive_ids, remove=["INBOX"])
                result["archived"]=len(archive_ids)
            except Exception as e:
                ERRS.append(f"archive batchModify: {e}")
            unread_after=list_all_messages("is:unread in:inbox")
            result["unreadAfter"]=[x["id"] for x in unread_after]
            result["leftUnread"]=len(result["unreadAfter"])
        else:
            result["leftUnread"]=len(keep_unread)
            result["unreadAfter"]=list(keep_unread)
            # Include plan rows as errors only in plan mode? Avoid final schema additions; print separate file instead.
            with open("/Users/dbochman/.openclaw/workspace/tmp/julia_gmail_triage_plan.json", "w") as f:
                json.dump({"result":result,"plan":plan_rows,"trashCandidates":trash_ids,"errors":ERRS}, f, indent=2)
        if ERRS:
            result["status"]="partial"
            result["errors"]=[e[:300] for e in ERRS]
        print(json.dumps(result, separators=(",",":")))
    except Exception as e:
        result["status"]="partial" if result["status"]=="ok" else result["status"]
        result["errors"]=(result.get("errors") or [])+[str(e)[:300]]+[x[:300] for x in ERRS]
        print(json.dumps(result, separators=(",",":")))

if __name__ == "__main__":
    main()
