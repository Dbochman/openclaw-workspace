#!/usr/bin/env python3
import base64, json, os, re, subprocess, sys, time
from email.utils import parseaddr

ACCOUNT = "julia.joy.jennings@gmail.com"
ENV = dict(os.environ, GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)
ERRS = []

def gws(parts, params=None, body=None):
    cmd = ["gws", "gmail"] + parts
    if params is not None:
        if "userId" not in params: params["userId"] = "me"
        cmd += ["--params", json.dumps(params, separators=(",", ":"))]
    if body is not None: cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    p = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[:500])
    try: out = json.loads(p.stdout or "{}")
    except Exception: raise RuntimeError("invalid JSON from gws")
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(str(out["error"])[:500])
    return out

def list_all(parts, q=None, key="messages"):
    items, token = [], None
    while True:
        p = {"userId":"me", "maxResults":100}
        if q is not None: p["q"] = q
        if token: p["pageToken"] = token
        out = gws(parts, p)
        items.extend(out.get(key, []))
        token = out.get("nextPageToken")
        if not token: return items

def headers(msg):
    return {h.get("name","").lower():h.get("value","") for h in msg.get("payload",{}).get("headers",[])}

def decode_body(msg):
    vals=[]
    def walk(p):
        mt=p.get("mimeType","")
        d=p.get("body",{}).get("data")
        if d and mt in ("text/plain","text/html"):
            try:
                s=base64.urlsafe_b64decode(d+"="*(-len(d)%4)).decode("utf-8","replace")
                if mt=="text/html": s=re.sub(r"<[^>]+>"," ",s)
                vals.append(s)
            except Exception: pass
        for x in p.get("parts",[]) or []: walk(x)
    walk(msg.get("payload",{}))
    return re.sub(r"\s+"," "," ".join(vals))[:12000]

def get_msg(mid): return gws(["users","messages","get"], {"userId":"me","id":mid,"format":"full"})

def summarize(msg):
    h=headers(msg)
    return {"id":msg.get("id"),"threadId":msg.get("threadId"),"from":h.get("from",""),"subject":h.get("subject",""),"date":h.get("date",""),"labels":msg.get("labelIds",[]),"snippet":msg.get("snippet","")}

def ensure_labels():
    names=["OpenClaw/Urgent","OpenClaw/Action","OpenClaw/FYI","OpenClaw/Financial","OpenClaw/Shopping","OpenClaw/Newsletters","OpenClaw/Social"]
    out=gws(["users","labels","list"],{"userId":"me"})
    mp={x["name"]:x["id"] for x in out.get("labels",[])}
    for n in names:
        if n not in mp:
            x=gws(["users","labels","create"],{"userId":"me"},{"name":n,"labelListVisibility":"labelShow","messageListVisibility":"show"})
            mp[n]=x["id"]
    return {n:mp[n] for n in names}

def phase_collect():
    labels=ensure_labels()
    promo=list_all(["users","messages","list"],"in:inbox category:promotions is:unread older_than:3d")
    full=[]
    for x in promo:
        try: full.append(get_msg(x["id"]))
        except Exception as e: ERRS.append({"id":x["id"],"stage":"promo_fetch","error":str(e)})
    unread_refs=list_all(["users","messages","list"],"is:unread in:inbox")
    unread=[]
    for x in unread_refs:
        try: unread.append(get_msg(x["id"]))
        except Exception as e: ERRS.append({"id":x["id"],"stage":"unread_fetch","error":str(e)})
    with open("tmp/julia_unread_full.json","w") as f: json.dump(unread,f)
    data={"labels":labels,"promo":[summarize(x) for x in full],"unread":[summarize(x) for x in unread],"errors":ERRS}
    with open("tmp/julia_collect.json","w") as f: json.dump(data,f,indent=2)
    print(json.dumps(data))

if __name__ == "__main__":
    phase_collect()
