#!/usr/bin/env python3
import base64, json, os, subprocess, time, re, email.utils
from email.message import EmailMessage
from pathlib import Path

ACCOUNT='julia.joy.jennings@gmail.com'
TODAY='2026-06-27'
OPENCLAW_LABELS=['OpenClaw/Urgent','OpenClaw/Action','OpenClaw/FYI','OpenClaw/Financial','OpenClaw/Shopping','OpenClaw/Newsletters','OpenClaw/Social']
PRIMARY_NAMES=['Urgent','Action','FYI','Financial','Shopping','Newsletters','Social']
ENV=os.environ.copy(); ENV['GOOGLE_WORKSPACE_CLI_ACCOUNT']=ACCOUNT
errors=[]

def run_gws(args, params=None, body=None, retry=True):
    params=dict(params or {})
    params.setdefault('userId','me')
    cmd=['gws']+args+['--params',json.dumps(params,separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body,separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=subprocess.run(cmd, text=True, capture_output=True, env=ENV)
    out=(p.stdout or '')+(('\n'+p.stderr) if p.stderr else '')
    if p.returncode!=0 and retry and 'Failed to get token' in out:
        time.sleep(5)
        return run_gws(args, params, body, retry=False)
    if p.returncode!=0:
        raise RuntimeError(out.strip()[:700])
    if not p.stdout.strip(): return {}
    try: return json.loads(p.stdout)
    except Exception as e: raise RuntimeError(('non-json: '+out.strip())[:700])

def list_all(q, kind='messages'):
    items=[]; token=None
    while True:
        params={'userId':'me','maxResults':100}
        if kind=='messages': params['q']=q
        if token: params['pageToken']=token
        data=run_gws(['gmail','users',kind,'list'], params)
        items.extend(data.get(kind,[]))
        token=data.get('nextPageToken')
        if not token: break
    return items

def get_msg(mid, fmt='full'):
    return run_gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':fmt})

def header(msg, name):
    for h in msg.get('payload',{}).get('headers',[]) or []:
        if h.get('name','').lower()==name.lower(): return h.get('value','')
    return ''

def decode_data(data):
    if not data: return ''
    try: return base64.urlsafe_b64decode(data + '='*((4-len(data)%4)%4)).decode('utf-8','replace')
    except Exception: return ''

def walk(part):
    texts=[]; mime=part.get('mimeType',''); body=part.get('body',{}) or {}
    if mime in ('text/plain','text/html') and body.get('data'):
        txt=decode_data(body.get('data'))
        if mime=='text/html':
            txt=re.sub(r'<(script|style)[^>]*>.*?</\\1>',' ',txt,flags=re.S|re.I)
            txt=re.sub(r'<br\\s*/?>','\n',txt,flags=re.I)
            txt=re.sub(r'<[^>]+>',' ',txt)
        texts.append(txt)
    for p in part.get('parts',[]) or []: texts.extend(walk(p))
    return texts

def body_text(msg):
    return re.sub(r'\s+',' ','\n'.join(walk(msg.get('payload',{}) or []))).strip()

def ensure_labels():
    data=run_gws(['gmail','users','labels','list'], {'userId':'me'})
    by={l.get('name'):l for l in data.get('labels',[])}
    for name in OPENCLAW_LABELS:
        if name not in by:
            run_gws(['gmail','users','labels','create'], {'userId':'me'}, {'name':name,'labelListVisibility':'labelShow','messageListVisibility':'show'})
    data=run_gws(['gmail','users','labels','list'], {'userId':'me'})
    by={l.get('name'):l for l in data.get('labels',[])}
    return {name:by[name]['id'] for name in OPENCLAW_LABELS}

def batch_modify(ids, add=None, remove=None):
    add=add or []; remove=remove or []
    for i in range(0,len(ids),1000):
        chunk=ids[i:i+1000]
        if not chunk: continue
        body={'ids':chunk}
        if add: body['addLabelIds']=add
        if remove: body['removeLabelIds']=remove
        run_gws(['gmail','users','messages','batchModify'], {'userId':'me'}, body)

def trash(mid):
    run_gws(['gmail','users','messages','trash'], {'userId':'me','id':mid})

def classify(msg):
    mid=msg.get('id','')
    subj=header(msg,'Subject')
    frm=header(msg,'From')
    text=(subj+' '+frm+' '+msg.get('snippet','')+' '+body_text(msg)[:2000]).lower()
    # Known reviewed messages from the 06:45 snapshot.
    known={
      '19f0880ae27d0276':'Shopping',
      '19f06a7564de405b':'Newsletters',
      '19f064a4efebf79f':'Shopping',
      '19f0632f400dabed':'Newsletters',
      '19f05861c25d91ce':'Newsletters',
      '19f04e6e991c815c':'Financial',
      '19f04db71ff925e2':'Shopping',
      '19f04d536cd4790f':'Newsletters',
      '19f047e690ef578a':'Shopping',
      '19f04716e3d3cac9':'Newsletters',
    }
    if mid in known: return known[mid], ''
    automated=bool(re.search(r'no-?reply|noreply|notification|alert|updates?|mailer|auto-|donotreply|info@|hello@|news|marketing|support@', frm.lower()))
    if any(w in text for w in ['delivered','delivery','shipment','shipped','order #','your order','receipt','purchase','tracking','package','review your recent purchase']): return 'Shopping',''
    if any(w in text for w in ['statement','payment','deposit','withdrawal','subscription renews','renewal price','bill','invoice','bank','credit card','transaction','tax','receipt for your payment']): return 'Financial',''
    if any(w in text for w in ['linkedin','facebook','instagram','calendar invitation','invited you','event update']): return 'Social',''
    if any(w in text for w in ['newsletter','unsubscribe','sale','% off','deal','promotion','job alert','digest','google alert','terms of service','marketing','ends tonight','waiting in your cart']): return 'Newsletters',''
    if (not automated) and re.search(r'\?|please reply|can you|could you|rsvp|let me know|would you|are you able|deadline|due today', text): return 'Action','Needs Julia to review/respond.'
    return ('FYI' if not automated else 'Newsletters'), ''

def is_clear_spam(msg):
    subj=header(msg,'Subject').lower(); frm=header(msg,'From').lower(); txt=(subj+' '+frm+' '+msg.get('snippet','')+' '+body_text(msg)[:1200]).lower()
    protected=['receipt','order','shipped','delivery','delivered','statement','payment','invoice','bank','security','password','appointment','travel','reservation','doctor','medical','legal','subscription renews']
    if any(p in txt for p in protected): return False
    marketing=['sale','% off','deal','promo','promotion','limited time','ends tonight','waiting in your cart','finish your order','new arrivals','shop now','discount']
    return any(m in txt for m in marketing) and ('unsubscribe' in txt or 'klaviyo' in frm or 'marketing' in frm or 'hello@' in frm or 'info@' in frm)

def base64url(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')

def create_reply_draft(source_msg, body):
    # Not expected for today's reviewed set, but kept safe for an obvious Action fallback.
    frm=email.utils.parseaddr(header(source_msg,'From'))[1]
    subj=header(source_msg,'Subject') or ''
    if not subj.lower().startswith('re:'): subj='Re: '+subj
    em=EmailMessage()
    em['To']=frm
    em['Subject']=subj
    em['In-Reply-To']=header(source_msg,'Message-ID')
    refs=' '.join(x for x in [header(source_msg,'References'), header(source_msg,'Message-ID')] if x).strip()
    if refs: em['References']=refs
    em.set_content(body)
    raw=base64.urlsafe_b64encode(bytes(em)).decode().rstrip('=')
    return run_gws(['gmail','users','drafts','create'], {'userId':'me'}, {'message':{'raw':raw,'threadId':source_msg.get('threadId')}})

# Auth check with retry per prompt.
try:
    run_gws(['gmail','users','messages','list'], {'userId':'me','q':'is:unread in:inbox','maxResults':1})
except Exception as e:
    time.sleep(5)
    try:
        run_gws(['gmail','users','messages','list'], {'userId':'me','q':'is:unread in:inbox','maxResults':1}, retry=False)
    except Exception as e2:
        print(json.dumps({'schemaVersion':1,'status':'auth_error','date':TODAY,'processed':0,'markedRead':0,'leftUnread':0,'draftsCreated':0,'draftsExisting':0,'archived':0,'trashed':0,'unreadAfter':[],'attention':[],'errors':['auth: '+str(e2)[:180]]},separators=(',',':')))
        raise SystemExit(0)

processed=markedRead=leftUnread=draftsCreated=draftsExisting=archived=trashed=0
attention=[]
try:
    label_map=ensure_labels()
    primary_ids=set(label_map.values())
    # 2. Remove clear spam (snapshot first).
    spam_items=list_all('in:inbox category:promotions is:unread older_than:3d')
    spam_ids=[m['id'] for m in spam_items]
    for mid in spam_ids:
        try:
            msg=get_msg(mid,'full')
            if is_clear_spam(msg):
                trash(mid); trashed+=1
        except Exception as e:
            errors.append(f'spam {mid}: {str(e)[:160]}')
    # 3. Complete unread inbox snapshot after spam removal.
    unread_items=list_all('is:unread in:inbox')
    unread_ids=[m['id'] for m in unread_items]
    # 4. Snapshot draft threads before any draft creation.
    draft_items=list_all('', kind='drafts')
    draft_threads={(d.get('message') or {}).get('threadId') for d in draft_items if (d.get('message') or {}).get('threadId')}

    by_label={name:[] for name in PRIMARY_NAMES}
    read_ids=[]
    remove_star_ids=[]
    for mid in unread_ids:
        try:
            msg=get_msg(mid,'full')
            processed+=1
            labelIds=set(msg.get('labelIds',[]))
            cls, reason=classify(msg)
            # No reviewed messages currently require a draft. Fallback Action messages are left unread for Julia.
            draft_status='none'
            needs_attention=False
            if cls=='Action':
                needs_attention=True
                if msg.get('threadId') in draft_threads:
                    draft_status='existing'; draftsExisting+=1
                # Avoid drafting for heuristic-only unknown messages; keep unread with reason.
            if cls=='Urgent': needs_attention=True
            by_label[cls].append(mid)
            if label_map['OpenClaw/Urgent'] in labelIds and cls!='Urgent' and 'STARRED' in labelIds:
                remove_star_ids.append(mid)
            if needs_attention:
                leftUnread+=1
                attention.append({'messageId':mid,'threadId':msg.get('threadId',''),'from':header(msg,'From'),'subject':header(msg,'Subject'),'reason':reason or ('Urgent/time-sensitive message.' if cls=='Urgent' else 'Needs Julia review.'),'deadline':'','draftStatus':draft_status})
            else:
                read_ids.append(mid)
        except Exception as e:
            processed+=1; leftUnread+=1
            errors.append(f'process {mid}: {str(e)[:160]}')
    for cls, ids in by_label.items():
        if not ids: continue
        add=[label_map['OpenClaw/'+cls]]
        rem=[lid for lid in primary_ids if lid not in add]
        try: batch_modify(ids, add=add, remove=rem)
        except Exception as e: errors.append(f'label {cls}: {str(e)[:160]}')
    if remove_star_ids:
        try: batch_modify(remove_star_ids, remove=['STARRED'])
        except Exception as e: errors.append(f'unstar stale urgent: {str(e)[:160]}')
    if read_ids:
        try:
            batch_modify(read_ids, remove=['UNREAD'])
            markedRead=len(read_ids)
        except Exception as e:
            errors.append(f'mark read: {str(e)[:160]}')
            # If failed, these may remain unread; count as left unread for consistency.
            leftUnread += len(read_ids)
            markedRead=0
    # 6. Archive stale read inbox mail; snapshot first.
    arch_items=list_all('is:read in:inbox older_than:1d')
    arch_ids=[m['id'] for m in arch_items]
    archive_ok=[]
    for mid in arch_ids:
        try:
            msg=get_msg(mid,'minimal')
            labs=set(msg.get('labelIds',[]))
            if 'STARRED' in labs or label_map['OpenClaw/Urgent'] in labs or label_map['OpenClaw/Action'] in labs:
                continue
            archive_ok.append(mid)
        except Exception as e:
            errors.append(f'archive-check {mid}: {str(e)[:160]}')
    if archive_ok:
        try:
            batch_modify(archive_ok, remove=['INBOX'])
            archived=len(archive_ok)
        except Exception as e:
            errors.append(f'archive: {str(e)[:160]}')
    unread_after=[m['id'] for m in list_all('is:unread in:inbox')]
except Exception as e:
    errors.append('fatal: '+str(e)[:200])
    try: unread_after=[m['id'] for m in list_all('is:unread in:inbox')]
    except Exception: unread_after=[]

result={'schemaVersion':1,'status':'partial' if errors else 'ok','date':TODAY,'processed':int(processed),'markedRead':int(markedRead),'leftUnread':int(leftUnread),'draftsCreated':int(draftsCreated),'draftsExisting':int(draftsExisting),'archived':int(archived),'trashed':int(trashed),'unreadAfter':unread_after,'attention':attention,'errors':errors}
Path('tmp/julia_triage_final.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
