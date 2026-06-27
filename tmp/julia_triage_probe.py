#!/usr/bin/env python3
import base64, json, os, subprocess, sys, time, re
from pathlib import Path

ACCOUNT='julia.joy.jennings@gmail.com'
OPENCLAW_LABELS=['OpenClaw/Urgent','OpenClaw/Action','OpenClaw/FYI','OpenClaw/Financial','OpenClaw/Shopping','OpenClaw/Newsletters','OpenClaw/Social']
ENV=os.environ.copy(); ENV['GOOGLE_WORKSPACE_CLI_ACCOUNT']=ACCOUNT

def run_gws(args, params=None, body=None, retry=True):
    params = dict(params or {})
    if args[:2] == ['gmail','users'] or (args and args[0]=='gmail'):
        params.setdefault('userId','me')
    cmd=['gws']+args
    if params is not None:
        cmd += ['--params', json.dumps(params, separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body, separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=subprocess.run(cmd, text=True, capture_output=True, env=ENV)
    out=(p.stdout or '')+(('\n'+p.stderr) if p.stderr else '')
    if p.returncode!=0 and retry and 'Failed to get token' in out:
        time.sleep(5)
        return run_gws(args, params, body, retry=False)
    if p.returncode!=0:
        raise RuntimeError(f"cmd failed {args}: {out[:500]}")
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except Exception:
        raise RuntimeError(f"non-json output for {args}: {out[:500]}")

def list_all_messages(q):
    ids=[]; token=None
    while True:
        params={'userId':'me','q':q,'maxResults':100}
        if token: params['pageToken']=token
        data=run_gws(['gmail','users','messages','list'], params)
        ids.extend([m['id'] for m in data.get('messages',[])])
        token=data.get('nextPageToken')
        if not token: break
    return ids

def list_all_drafts():
    drafts=[]; token=None
    while True:
        params={'userId':'me','maxResults':100}
        if token: params['pageToken']=token
        data=run_gws(['gmail','users','drafts','list'], params)
        drafts.extend(data.get('drafts',[]))
        token=data.get('nextPageToken')
        if not token: break
    return drafts

def get_msg(mid, fmt='full'):
    return run_gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':fmt})

def header(msg, name):
    for h in msg.get('payload',{}).get('headers',[]):
        if h.get('name','').lower()==name.lower(): return h.get('value','')
    return ''

def decode_data(data):
    if not data: return ''
    try:
        return base64.urlsafe_b64decode(data + '='*((4-len(data)%4)%4)).decode('utf-8','replace')
    except Exception:
        return ''

def walk_parts(part):
    texts=[]
    mime=part.get('mimeType','')
    body=part.get('body',{})
    if mime in ('text/plain','text/html') and body.get('data'):
        txt=decode_data(body.get('data'))
        if mime=='text/html':
            txt=re.sub(r'<(script|style)[^>]*>.*?</\\1>',' ',txt,flags=re.S|re.I)
            txt=re.sub(r'<br\\s*/?>','\n',txt,flags=re.I)
            txt=re.sub(r'<[^>]+>',' ',txt)
        texts.append(txt)
    for p in part.get('parts',[]) or []:
        texts.extend(walk_parts(p))
    return texts

def body_text(msg):
    txt='\n'.join(walk_parts(msg.get('payload',{})))
    txt=re.sub(r'\s+',' ',txt).strip()
    return txt

def summarize(mid):
    msg=get_msg(mid,'full')
    b=body_text(msg)
    return {
        'id': mid,
        'threadId': msg.get('threadId',''),
        'labelIds': msg.get('labelIds',[]),
        'from': header(msg,'From'),
        'to': header(msg,'To'),
        'date': header(msg,'Date'),
        'subject': header(msg,'Subject'),
        'messageIdHeader': header(msg,'Message-ID'),
        'references': header(msg,'References'),
        'inReplyTo': header(msg,'In-Reply-To'),
        'snippet': msg.get('snippet',''),
        'bodyExcerpt': b[:1200]
    }

def ensure_labels():
    data=run_gws(['gmail','users','labels','list'], {'userId':'me'})
    labels=data.get('labels',[])
    byname={l.get('name'):l for l in labels}
    created=[]
    for name in OPENCLAW_LABELS:
        if name not in byname:
            run_gws(['gmail','users','labels','create'], {'userId':'me'}, {'name':name,'labelListVisibility':'labelShow','messageListVisibility':'show'})
            created.append(name)
    data=run_gws(['gmail','users','labels','list'], {'userId':'me'})
    labels=data.get('labels',[])
    byname={l.get('name'):l for l in labels}
    return {name:byname[name]['id'] for name in OPENCLAW_LABELS}, created

label_map, created = ensure_labels()
spam_ids=list_all_messages('in:inbox category:promotions is:unread older_than:3d')
unread_ids=list_all_messages('is:unread in:inbox')
drafts=list_all_drafts()
out={
  'createdLabels': created,
  'labelMap': label_map,
  'spamCount': len(spam_ids),
  'spam': [summarize(mid) for mid in spam_ids[:200]],
  'unreadCount': len(unread_ids),
  'unread': [summarize(mid) for mid in unread_ids],
  'draftThreadIds': sorted({(d.get('message') or {}).get('threadId','') for d in drafts if (d.get('message') or {}).get('threadId')})
}
Path('tmp/julia_triage_probe_output.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps({'ok': True, 'spamCount': len(spam_ids), 'unreadCount': len(unread_ids), 'draftThreads': len(out['draftThreadIds']), 'createdLabels': created}))
