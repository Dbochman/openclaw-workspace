#!/usr/bin/env python3
import base64, json, os, re, subprocess, sys
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr
from zoneinfo import ZoneInfo

ACCOUNT = "julia.joy.jennings@gmail.com"
LABEL_NAMES = ["OpenClaw/Urgent","OpenClaw/Action","OpenClaw/FYI","OpenClaw/Financial","OpenClaw/Shopping","OpenClaw/Newsletters","OpenClaw/Social"]
TODAY = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
errors=[]

def call(parts, params=None, body=None):
    env=os.environ.copy(); env["GOOGLE_WORKSPACE_CLI_ACCOUNT"]=ACCOUNT
    cmd=["gws","gmail"]+parts
    if params is not None: cmd += ["--params",json.dumps(params,separators=(",",":"))]
    if body is not None: cmd += ["--json",json.dumps(body,separators=(",",":"))]
    p=subprocess.run(cmd,env=env,text=True,capture_output=True)
    out=(p.stdout or "")+(p.stderr or "")
    if p.returncode: raise RuntimeError(out.strip()[:300])
    try: data=json.loads(p.stdout) if p.stdout.strip() else {}
    except Exception: raise RuntimeError("non-JSON Gmail response")
    if isinstance(data,dict) and data.get("error"): raise RuntimeError(str(data["error"])[:300])
    return data

def paged(parts, key, params):
    items=[]; token=None
    while True:
        p=dict(params); p["userId"]="me"; p["maxResults"]=100
        if token: p["pageToken"]=token
        d=call(parts,p); items.extend(d.get(key,[]) or [])
        token=d.get("nextPageToken")
        if not token: return items

def headers(msg):
    out={}
    for h in msg.get("payload",{}).get("headers",[]) or []:
        n=h.get("name","").lower()
        try: v=str(make_header(decode_header(h.get("value",""))))
        except Exception: v=h.get("value","")
        out[n]=v
    return out

def decode64(s):
    try: return base64.urlsafe_b64decode(s + "="*((4-len(s)%4)%4)).decode("utf-8","replace")
    except Exception: return ""

def body_text(part):
    texts=[]
    mime=part.get("mimeType","")
    data=(part.get("body") or {}).get("data")
    if data and mime in ("text/plain","text/html"):
        t=decode64(data)
        if mime=="text/html": t=re.sub(r"<[^>]+>"," ",t)
        texts.append(t)
    for c in part.get("parts",[]) or []: texts.append(body_text(c))
    return " ".join(texts)

def text(msg):
    return " ".join([msg.get("snippet","") or "", body_text(msg.get("payload",{}))])[:30000]

def automated(frm, hdr, txt):
    s=(frm+" "+hdr.get("list-unsubscribe","")+" "+hdr.get("precedence","")+" "+txt[:500]).lower()
    return any(x in s for x in ["no-reply","noreply","donotreply","do-not-reply","mailer-daemon","list-unsubscribe","unsubscribe","notification@","alerts@","updates@"])

def classify(msg):
    h=headers(msg); frm=h.get("from",""); subj=h.get("subject",""); t=text(msg)
    s=(frm+" "+subj+" "+t[:5000]).lower()
    auto=automated(frm,h,t)
    sensitive=any(x in s for x in ["medical","patient","health record","legal notice","attorney","court ","diagnosis","test result"])
    unexpected=any(x in s for x in ["payment failed","payment declined","past due","overdue","account suspended","account locked","unauthorized","unrecognized","security alert","fraud alert","password changed","recovery email changed"])
    deadline=""
    md=re.search(r"(?:due|deadline|respond by|rsvp by)\s*(?:on\s*)?([^\n\r,.]{3,40})",t,re.I)
    if md: deadline=md.group(1).strip()[:80]
    if unexpected or (not auto and any(x in s for x in ["urgent","today","asap","time-sensitive"])):
        return "Urgent",True,deadline,"Time-sensitive or unexpected account/payment issue."
    if any(x in s for x in ["invoice","statement available","monthly statement","bill is ready","payment received","payment confirmation","deposit","withdrawal","bank notice","credit card","autopay","tax document","refund issued","venmo","paypal","zelle","mortgage"]):
        return "Financial",sensitive,deadline,"Routine financial notice."
    if any(x in s for x in ["order #","order confirmation","your order","has shipped","shipping update","out for delivery","delivered","purchase receipt","your receipt","tracking number","amazon.com","etsy","shopify"]):
        return "Shopping",False,deadline,"Order, receipt, shipping, or delivery update."
    if any(x in s for x in ["calendar invitation","invitation:","event updated","event canceled","event cancelled","facebook","instagram","linkedin","nextdoor","evite","partiful","luma","meetup"]):
        return "Social",False,deadline,"Calendar, event, or social notification."
    newsletter=auto or any(x in s for x in ["newsletter","digest","weekly update","daily update","google alert","job alert","new jobs","sale","% off","promotion","unsubscribe","marketing","recommended for you"])
    directq=("?" in (subj+" "+t[:2500]))
    action_words=any(x in s for x in ["please reply","please respond","can you","could you","would you","let me know","rsvp","need your","action required","complete the","sign the","review and approve","confirm your"])
    if not auto and (directq or action_words):
        return "Action",True,deadline,"A reply or concrete action appears to be requested."
    if newsletter: return "Newsletters",False,deadline,"Subscription, digest, alert, or promotional mail."
    return "FYI",sensitive,deadline,"Informational message from a person."

def clear_spam(msg):
    h=headers(msg); s=(h.get("from","")+" "+h.get("subject","")+" "+text(msg)[:2500]).lower()
    protected=["receipt","order","shipped","delivery","statement","bill","payment","bank","account","security","travel","flight","hotel","medical","health","legal","appointment","reservation","ticket","subscription renewal"]
    if any(x in s for x in protected): return False
    promo=any(x in s for x in ["% off","sale ends","limited time offer","flash sale","shop now","buy now","clearance","promo code","exclusive offer","save $","free shipping","last chance"])
    return promo and automated(h.get("from",""),h,text(msg))

def batch(ids, add=None, remove=None):
    if not ids: return
    for i in range(0,len(ids),1000):
        call(["users","messages","batchModify"],{"userId":"me"},{"ids":ids[i:i+1000],"addLabelIds":add or [],"removeLabelIds":remove or []})

result={"schemaVersion":1,"status":"ok","date":TODAY,"processed":0,"markedRead":0,"leftUnread":0,"draftsCreated":0,"draftsExisting":0,"archived":0,"trashed":0,"unreadAfter":[],"attention":[],"errors":errors}

try:
    labs=call(["users","labels","list"],{"userId":"me"}).get("labels",[]) or []
    byname={x.get("name"):x.get("id") for x in labs}
    for name in LABEL_NAMES:
        if not byname.get(name):
            d=call(["users","labels","create"],{"userId":"me"},{"name":name,"labelListVisibility":"labelShow","messageListVisibility":"show"})
            byname[name]=d["id"]
except Exception as e:
    errors.append("label setup failed: "+str(e)); result["status"]="partial"
    print(json.dumps(result,separators=(",",":"))); sys.exit(0)

# Clear only unmistakable old promotions.
try: spamrefs=paged(["users","messages","list"],"messages",{"q":"in:inbox category:promotions is:unread older_than:3d"})
except Exception as e: spamrefs=[]; errors.append("spam list failed: "+str(e)); result["status"]="partial"
for ref in spamrefs:
    try:
        m=call(["users","messages","get"],{"userId":"me","id":ref["id"],"format":"full"})
        if clear_spam(m): call(["users","messages","trash"],{"userId":"me","id":ref["id"]}); result["trashed"]+=1
    except Exception as e: errors.append("spam processing failed for "+ref.get("id","")+": "+str(e)); result["status"]="partial"

try: refs=paged(["users","messages","list"],"messages",{"q":"is:unread in:inbox"})
except Exception as e:
    errors.append("unread list failed: "+str(e)); result["status"]="partial"; refs=[]
msgs=[]
for ref in refs:
    try: msgs.append(call(["users","messages","get"],{"userId":"me","id":ref["id"],"format":"full"}))
    except Exception as e: errors.append("fetch failed for "+ref.get("id","")+": "+str(e)); result["status"]="partial"
result["processed"]=len(msgs)

try:
    drafts=paged(["users","drafts","list"],"drafts",{})
    draft_threads={d.get("message",{}).get("threadId") for d in drafts if d.get("message",{}).get("threadId")}
except Exception as e: drafts=[]; draft_threads=set(); errors.append("draft list failed: "+str(e)); result["status"]="partial"

plans=[]
for m in msgs:
    kind,keep,deadline,reason=classify(m); h=headers(m); frm=h.get("from",""); subj=h.get("subject","")
    draft_status="none"
    if kind=="Action":
        try:
            th=call(["users","threads","get"],{"userId":"me","id":m["threadId"],"format":"full"})
            chronological=sorted(th.get("messages",[]) or [],key=lambda x:int(x.get("internalDate",0)))
            latest=chronological[-1] if chronological else m; lh=headers(latest); latest_from=parseaddr(lh.get("from",""))[1].lower()
            julia_replied=latest_from==ACCOUNT.lower()
            if julia_replied:
                kind="FYI"; keep=False; reason="Julia already replied; thread appears resolved."
            elif m["threadId"] in draft_threads:
                draft_status="existing"; result["draftsExisting"]+=1; keep=True
            elif not automated(frm,h,text(m)) and ("?" in (subj+" "+text(m)[:2500]) or any(x in text(m).lower() for x in ["please reply","please respond","let me know","can you","could you","would you"])):
                to_addr=parseaddr(frm)[1]
                msgid=lh.get("message-id","")
                refs=(lh.get("references","")+" "+msgid).strip()
                rs=subj if subj.lower().startswith("re:") else "Re: "+subj
                first=(parseaddr(frm)[0].split() or [""])[0].strip('"')
                greeting=("Hi "+first+",") if first else "Hello,"
                reply=greeting+"\r\n\r\nThanks for reaching out. I saw your message and will take a look. I’ll follow up shortly.\r\n\r\nBest,\r\nJulia"
                raw=(f"To: {to_addr}\r\nSubject: {rs}\r\nIn-Reply-To: {msgid}\r\nReferences: {refs}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{reply}")
                enc=base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
                call(["users","drafts","create"],{"userId":"me"},{"message":{"threadId":m["threadId"],"raw":enc}})
                draft_status="created"; result["draftsCreated"]+=1; keep=True; draft_threads.add(m["threadId"])
            else:
                keep=True; reason="Concrete action only Julia can take; no reply draft is appropriate."
        except Exception as e:
            keep=True; errors.append("thread/draft processing failed for "+m["id"]+": "+str(e)); result["status"]="partial"
    plans.append({"m":m,"kind":kind,"keep":keep,"deadline":deadline,"reason":reason,"draft":draft_status,"from":frm,"subject":subj})

# Apply exactly one primary label; group identical mutations.
groups={}
primary_ids=[byname[n] for n in LABEL_NAMES]
for p in plans:
    m=p["m"]; old=set(m.get("labelIds",[]) or []); add=[byname["OpenClaw/"+p["kind"]]]; rem=list(primary_ids)
    if p["kind"]=="Urgent": add.append("STARRED")
    elif byname["OpenClaw/Urgent"] in old and "STARRED" in old: rem.append("STARRED")
    rem=[x for x in rem if x not in set(add)]
    key=(tuple(sorted(set(add))),tuple(sorted(set(rem))))
    groups.setdefault(key,[]).append(m["id"])
failed=set()
for (add,rem),ids in groups.items():
    try: batch(ids,list(add),list(rem))
    except Exception as e:
        failed.update(ids); errors.append("label update failed for batch: "+str(e)); result["status"]="partial"

for p in plans:
    if p["m"]["id"] in failed: p["keep"]=True
    if p["keep"]:
        result["leftUnread"]+=1
        if p["m"]["id"] not in failed:
            result["attention"].append({"messageId":p["m"]["id"],"threadId":p["m"]["threadId"],"from":p["from"],"subject":p["subject"],"reason":p["reason"],"deadline":p["deadline"],"draftStatus":p["draft"]})

read_ids=[p["m"]["id"] for p in plans if not p["keep"] and p["m"]["id"] not in failed]
try: batch(read_ids,[],["UNREAD"]); result["markedRead"]=len(read_ids)
except Exception as e: errors.append("mark-read failed: "+str(e)); result["status"]="partial"; result["leftUnread"]+=len(read_ids)

# Archive stale read mail after read-state changes, excluding attention labels and stars.
try: stale=paged(["users","messages","list"],"messages",{"q":"is:read in:inbox older_than:1d"})
except Exception as e: stale=[]; errors.append("archive list failed: "+str(e)); result["status"]="partial"
archive=[]
for ref in stale:
    try:
        m=call(["users","messages","get"],{"userId":"me","id":ref["id"],"format":"full"}); ls=set(m.get("labelIds",[]) or [])
        if not ({byname["OpenClaw/Urgent"],byname["OpenClaw/Action"],"STARRED"} & ls): archive.append(m["id"])
    except Exception as e: errors.append("archive fetch failed for "+ref.get("id","")+": "+str(e)); result["status"]="partial"
try: batch(archive,[],["INBOX"]); result["archived"]=len(archive)
except Exception as e: errors.append("archive update failed: "+str(e)); result["status"]="partial"

try: result["unreadAfter"]=[x["id"] for x in paged(["users","messages","list"],"messages",{"q":"is:unread in:inbox"})]
except Exception as e: errors.append("final unread list failed: "+str(e)); result["status"]="partial"
result["leftUnread"]=len(result["unreadAfter"])
print(json.dumps(result,separators=(",",":")))
