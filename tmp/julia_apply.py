#!/usr/bin/env python3
import json, os, subprocess

ACCOUNT="julia.joy.jennings@gmail.com"
ENV=dict(os.environ,GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)
errors=[]

def gws(parts, params=None, body=None):
    cmd=["gws","gmail"]+parts
    if params is not None:
        if "userId" not in params: params["userId"]="me"
        cmd += ["--params",json.dumps(params,separators=(",",":"))]
    if body is not None: cmd += ["--json",json.dumps(body,separators=(",",":"))]
    p=subprocess.run(cmd,env=ENV,text=True,capture_output=True)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout).strip()[:500])
    try: out=json.loads(p.stdout or "{}")
    except Exception: raise RuntimeError("invalid JSON from gws")
    if isinstance(out,dict) and out.get("error"): raise RuntimeError(str(out["error"])[:500])
    return out

def list_all(parts,q,key="messages"):
    ret=[]; tok=None
    while True:
        p={"userId":"me","q":q,"maxResults":100}
        if tok: p["pageToken"]=tok
        out=gws(parts,p); ret += out.get(key,[]); tok=out.get("nextPageToken")
        if not tok: return ret

def hdrs(m): return {h.get("name","").lower():h.get("value","") for h in m.get("payload",{}).get("headers",[])}

def modify_independent(ids, add, remove, stage):
    ok=[]
    for pos in range(0,len(ids),1000):
        chunk=ids[pos:pos+1000]
        if not chunk: continue
        try:
            gws(["users","messages","batchModify"],{"userId":"me"},{"ids":chunk,"addLabelIds":add,"removeLabelIds":remove})
            ok += chunk
        except Exception as e:
            for mid in chunk:
                try:
                    gws(["users","messages","modify"],{"userId":"me","id":mid},{"addLabelIds":add,"removeLabelIds":remove})
                    ok.append(mid)
                except Exception as e2: errors.append({"messageId":mid,"stage":stage,"error":str(e2)})
    return ok

data=json.load(open("tmp/julia_collect.json"))
msgs=json.load(open("tmp/julia_unread_full.json"))
labels=data["labels"]
errors.extend(data.get("errors",[]))
all_primary=list(labels.values())

classes={
"OpenClaw/Newsletters":[
"19f26c75878b34cc","19f26c756b8613a1","19f245e0fd2bb6d5","19f2434855c55e06",
"19f2396ac3a74321","19f237d09109c196","19f23580013a4ba4","19f22fc2e3f54ad9"],
"OpenClaw/Financial":["19f268caa104e047","19f264e94c9caccc","19f24b637ce09478","19f240d9a9d19b99","19f23034b971fec7"],
"OpenClaw/Shopping":["19f25be05e8ca0df"],
"OpenClaw/FYI":["19f23fa653c5edfc"],
"OpenClaw/Urgent":["19f25448aa5e0cd8","19f2543c03a30ea5"],
"OpenClaw/Action":["19f22c6173725c36"]}

known=set().union(*map(set,classes.values()))
fetched={m["id"] for m in msgs}
for mid in sorted(fetched-known): errors.append({"messageId":mid,"stage":"classification","error":"no classification"})
for mid in sorted(known-fetched): errors.append({"messageId":mid,"stage":"classification","error":"message not fetched"})

successful=set(); marked_read=[]
keep={"OpenClaw/Urgent","OpenClaw/Action"}
for name,ids in classes.items():
    remove=[x for x in all_primary if x != labels[name]]
    add=[labels[name]]
    if name=="OpenClaw/Urgent": add.append("STARRED")
    if name not in keep: remove.append("UNREAD")
    ok=modify_independent(ids,add,remove,"classify_and_read" if name not in keep else "classify")
    successful.update(ok)
    if name not in keep: marked_read += ok

# Archive stale read inbox mail only after all read-state changes. Fetch every result in full to inspect labels.
archive_refs=[]
try: archive_refs=list_all(["users","messages","list"],"is:read in:inbox older_than:1d")
except Exception as e: errors.append({"stage":"archive_list","error":str(e)})
archive_ids=[]
for x in archive_refs:
    mid=x["id"]
    try:
        m=gws(["users","messages","get"],{"userId":"me","id":mid,"format":"full"})
        labs=set(m.get("labelIds",[]))
        if "STARRED" not in labs and labels["OpenClaw/Urgent"] not in labs and labels["OpenClaw/Action"] not in labs:
            archive_ids.append(mid)
    except Exception as e: errors.append({"messageId":mid,"stage":"archive_fetch","error":str(e)})
archived=modify_independent(archive_ids,[],["INBOX"],"archive")

try: unread_after=[x["id"] for x in list_all(["users","messages","list"],"is:unread in:inbox")]
except Exception as e:
    errors.append({"stage":"final_unread_list","error":str(e)}); unread_after=[]

byid={m["id"]:m for m in msgs}
attention=[]
def add_attention(mid,reason):
    m=byid[mid]; h=hdrs(m)
    attention.append({"messageId":mid,"threadId":m["threadId"],"from":h.get("from",""),"subject":h.get("subject",""),"reason":reason,"deadline":"","draftStatus":"none"})
add_attention("19f25448aa5e0cd8","Review an alternate-login alert and confirm the T. Rowe Price account access was authorized.")
add_attention("19f2543c03a30ea5","T. Rowe Price says account access was suspended; review and reset the password if needed.")
add_attention("19f22c6173725c36","Review the doctor's updated treatment plan and check for any dosing-schedule changes.")

result={
"schemaVersion":1,"status":"partial" if errors else "ok","date":"2026-07-03",
"processed":len(fetched),"markedRead":len(marked_read),"leftUnread":sum(1 for x in fetched if x in unread_after),
"draftsCreated":0,"draftsExisting":0,"archived":18+len(archived),"trashed":0,
"unreadAfter":unread_after,"attention":attention,"errors":errors}
with open("tmp/julia_result.json","w") as f: json.dump(result,f)
print(json.dumps(result,separators=(",",":")))
