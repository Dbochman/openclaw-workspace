#!/usr/bin/env python3
import subprocess, json, sys, time, base64, re, html, email.utils
from collections import defaultdict
ACCOUNT='julia.joy.jennings@gmail.com'
DATE='2026-06-24'
OPENCLAW_LABELS=['OpenClaw/Urgent','OpenClaw/Action','OpenClaw/FYI','OpenClaw/Financial','OpenClaw/Shopping','OpenClaw/Newsletters','OpenClaw/Social']
errors=[]

result={
  'schemaVersion':1,'status':'ok','date':DATE,'processed':0,'markedRead':0,'leftUnread':0,
  'draftsCreated':0,'draftsExisting':0,'archived':0,'trashed':0,'unreadAfter':[], 'attention':[], 'errors':[]
}

def gws(resource, method, params=None, body=None, timeout=120):
    cmd=['gws','gmail']+resource.split()+[method]
    if params is not None:
        cmd += ['--params', json.dumps(params,separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body,separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)
    if p.returncode!=0:
        raise RuntimeError((p.stderr or p.stdout or 'gws failed').strip()[:500])
    return json.loads(p.stdout) if p.stdout.strip() else {}

def list_all(kind, q=None):
    ids=[]; token=None
    while True:
        params={'userId':'me','maxResults':100}
        if q is not None: params['q']=q
        if token: params['pageToken']=token
        if kind=='messages':
            d=gws('users messages','list',params)
            ids.extend([m['id'] for m in d.get('messages',[])])
        elif kind=='drafts':
            d=gws('users drafts','list',params)
            ids.extend([dft.get('message',{}).get('threadId') for dft in d.get('drafts',[]) if dft.get('message',{}).get('threadId')])
        token=d.get('nextPageToken')
        if not token: return ids

def batch_modify(ids, add=None, remove=None):
    add=add or []; remove=remove or []
    for i in range(0,len(ids),1000):
        chunk=ids[i:i+1000]
        if chunk:
            gws('users messages','batchModify',{'userId':'me'},{'ids':chunk,'addLabelIds':add,'removeLabelIds':remove})

def get_msg(mid):
    return gws('users messages','get',{'userId':'me','id':mid,'format':'full'})

def headers(msg):
    return {h.get('name','').lower():h.get('value','') for h in msg.get('payload',{}).get('headers',[])}

def ensure_labels():
    d=gws('users labels','list',{'userId':'me'})
    by_name={l.get('name'):l.get('id') for l in d.get('labels',[])}
    for name in OPENCLAW_LABELS:
        if name not in by_name:
            created=gws('users labels','create',{'userId':'me'},{'name':name,'labelListVisibility':'labelShow','messageListVisibility':'show'})
            by_name[name]=created.get('id')
    return {name:by_name[name] for name in OPENCLAW_LABELS}

def is_obvious_spam(msg):
    h=headers(msg); subj=h.get('subject','').lower(); frm=h.get('from','').lower(); snip=(msg.get('snippet','') or '').lower()
    text=' '.join([subj,frm,snip])
    protected=['receipt','order','shipped','delivered','delivery','statement','bill','payment','appointment','reservation','booking','security','password','sign-in','signin','account','bank','treasury','doctor','medical','legal','travel','flight','hotel']
    if any(x in text for x in protected): return False
    promo=['sale','discount','% off','limited time','clearance','deal','offer','unsubscribe','shop now','ends tonight','coupon','promo']
    return any(x in text for x in promo)

try:
    label_ids=ensure_labels()
    primary_ids=[label_ids[n] for n in OPENCLAW_LABELS]
    # Step 2: spam removal snapshot
    spam_ids=list_all('messages','in:inbox category:promotions is:unread older_than:3d')
    trashed=[]
    for mid in spam_ids:
        try:
            msg=get_msg(mid)
            if is_obvious_spam(msg):
                gws('users messages','trash',{'userId':'me','id':mid})
                trashed.append(mid)
        except Exception as e:
            errors.append(f'spam:{mid}:{str(e)[:120]}')
    result['trashed']=len(trashed)

    # Step 3: unread inbox snapshot and full fetch
    unread_ids=list_all('messages','is:unread in:inbox')
    messages={}
    for mid in unread_ids:
        try:
            messages[mid]=get_msg(mid)
        except Exception as e:
            errors.append(f'fetch:{mid}:{str(e)[:120]}')
    result['processed']=len(messages)

    # Step 4: draft thread snapshot (fully paginated)
    draft_threads=set()
    try:
        draft_threads=set(list_all('drafts'))
    except Exception as e:
        errors.append(f'drafts_list:{str(e)[:160]}')

    classifications={}
    attention=[]
    # The current unread snapshot was inspected in full immediately before mutation.
    for mid,msg in messages.items():
        h=headers(msg); frm=h.get('from',''); subj=h.get('subject','')
        labels=set(msg.get('labelIds',[])); thread=msg.get('threadId','')
        if mid in ('19ef7662cea1b276','19ef765fe44de0ee'):
            classifications[mid]='OpenClaw/Shopping'
        elif mid=='19ef536433778b03':
            classifications[mid]='OpenClaw/Social'
        elif mid=='19ea87a05e60456d':
            classifications[mid]='OpenClaw/Financial'
            attention.append({'messageId':mid,'threadId':thread,'from':frm,'subject':subj,
                              'reason':'TreasuryDirect says there is an important message in Julia’s Investor InBox that only she can review.',
                              'deadline':'','draftStatus':'none'})
        else:
            # conservative fallback if a new unread arrived after inspection
            text=(frm+' '+subj+' '+(msg.get('snippet','') or '')).lower()
            if any(k in text for k in ['order','shipped','delivered','delivery','receipt']): cls='OpenClaw/Shopping'
            elif any(k in text for k in ['treasury','bank','payment','statement','bill','deposit','invoice']): cls='OpenClaw/Financial'
            elif any(k in text for k in ['invitation','appointment','event','calendar','confirmation']): cls='OpenClaw/Social'
            elif any(k in text for k in ['newsletter','digest','alert','sale','unsubscribe','promotion']): cls='OpenClaw/Newsletters'
            else: cls='OpenClaw/FYI'
            classifications[mid]=cls

    # Apply labels by selected classification. Urgent would receive STARRED; none in this snapshot.
    by_cls=defaultdict(list)
    for mid,cls in classifications.items(): by_cls[cls].append(mid)
    for cls,ids in by_cls.items():
        try:
            add=[label_ids[cls]]
            if cls=='OpenClaw/Urgent': add.append('STARRED')
            batch_modify(ids, add=add, remove=primary_ids)
        except Exception as e:
            errors.append(f'label:{cls}:{str(e)[:160]}')

    # Mark routine reviewed messages read; keep attention/failure messages unread.
    keep_unread={a['messageId'] for a in attention}
    failed_ids={e.split(':')[1] for e in errors if e.startswith(('fetch:','label:','draft:','read:')) and len(e.split(':'))>1}
    keep_unread |= (failed_ids & set(unread_ids))
    mark_read=[mid for mid in messages if mid not in keep_unread]
    if mark_read:
        try:
            batch_modify(mark_read, remove=['UNREAD'])
            result['markedRead']=len(mark_read)
        except Exception as e:
            errors.append(f'read:{str(e)[:160]}')
            keep_unread.update(mark_read)
            result['markedRead']=0
    result['attention']=attention

    # Step 6: archive stale read inbox mail, snapshot then fetch/skip Action/Urgent/STARRED.
    stale_ids=list_all('messages','is:read in:inbox older_than:1d')
    archive=[]
    skip={label_ids['OpenClaw/Urgent'], label_ids['OpenClaw/Action'], 'STARRED'}
    for mid in stale_ids:
        try:
            msg=get_msg(mid)
            if not (set(msg.get('labelIds',[])) & skip):
                archive.append(mid)
        except Exception as e:
            errors.append(f'archive_fetch:{mid}:{str(e)[:120]}')
    if archive:
        try:
            batch_modify(archive, remove=['INBOX'])
            result['archived']=len(archive)
        except Exception as e:
            errors.append(f'archive:{str(e)[:160]}')
            result['archived']=0

    final_unread=list_all('messages','is:unread in:inbox')
    result['unreadAfter']=final_unread
    result['leftUnread']=len(final_unread)
except Exception as e:
    errors.append(f'fatal:{str(e)[:200]}')

if errors:
    result['status']='partial'
result['errors']=errors
print(json.dumps(result,separators=(',',':'),ensure_ascii=False))
