import base64, datetime as dt, json, os, re, subprocess, sys, textwrap
from email.utils import parseaddr

ACCOUNT='julia.joy.jennings@gmail.com'
REQ_LABELS=['Urgent','Action','FYI','Financial','Shopping','Newsletters','Social']
FULL_LABELS=[f'OpenClaw/{x}' for x in REQ_LABELS]
TODAY='2026-06-22'
TOMORROW='2026-06-23'
OFFSET='-04:00'

def run(cmd, input=None, check=True, text=True):
    p=subprocess.run(cmd, input=input, capture_output=True, text=text)
    if check and p.returncode!=0:
        raise RuntimeError((p.stderr or '')+(p.stdout or ''))
    return p

def gws(service_args, params=None, body=None, check=True):
    cmd=['gws']+service_args
    if params is not None:
        cmd += ['--params', json.dumps(params, separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body, separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=run(cmd, check=check)
    out=p.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return out

def as_list_labels(resp):
    if isinstance(resp, dict):
        return resp.get('labels') or resp.get('items') or []
    return resp if isinstance(resp,list) else []

def messages_from(resp):
    if isinstance(resp, dict):
        return resp.get('messages') or []
    if isinstance(resp, list):
        return resp
    return []

def hdrs(msg):
    arr=(((msg or {}).get('payload') or {}).get('headers') or [])
    d={}
    for h in arr:
        n=h.get('name','')
        if n and n.lower() not in d:
            d[n.lower()]=h.get('value','')
    return d

def decode_body(payload):
    texts=[]
    def rec(part):
        mime=part.get('mimeType','')
        data=(part.get('body') or {}).get('data')
        if data and (mime.startswith('text/plain') or mime.startswith('text/html')):
            try:
                raw=base64.urlsafe_b64decode(data + '='*((4-len(data)%4)%4))
                s=raw.decode('utf-8','ignore')
                if mime.startswith('text/html'):
                    s=re.sub(r'<(br|p|div|li|tr)[^>]*>', '\n', s, flags=re.I)
                    s=re.sub(r'<[^>]+>', '', s)
                    s=re.sub(r'&nbsp;', ' ', s)
                    s=re.sub(r'&amp;', '&', s)
                texts.append(s)
            except Exception:
                pass
        for ch in part.get('parts') or []:
            rec(ch)
    rec(payload or {})
    return '\n'.join(texts).strip()

def email_addr(fromv):
    return parseaddr(fromv)[1].lower()

def display_name(fromv):
    name, addr=parseaddr(fromv)
    if name:
        return re.sub(r'"','',name).strip()
    return addr.split('@')[0] if addr else fromv

automated_tokens=['no-reply','noreply','donotreply','do-not-reply','notification','notifications','marketing','newsletter','news','offers','promo','promotions','support','alerts','alert','updates','receipts','receipt','billing','statements','statement','auto']
def is_real_person(fromv):
    addr=email_addr(fromv); local=addr.split('@')[0] if '@' in addr else addr
    name=display_name(fromv).lower()
    if any(t in local for t in automated_tokens): return False
    if any(t in name for t in ['noreply','no reply','notification','newsletter','team','support','service','billing']): return False
    # Obvious platforms/domains are not people
    domain=addr.split('@')[-1] if '@' in addr else ''
    if domain in ['facebookmail.com','instagram.com','linkedin.com','twitter.com','x.com','tiktok.com','mailchimpapp.net','substack.com','medium.com','spotify.com','amazon.com','accounts.google.com','google.com']:
        return False
    return bool(addr)

def classify(fromv, subj, snippet, body):
    text=' '.join([fromv,subj,snippet or '', body[:1000] if body else '']).lower()
    subj_l=(subj or '').lower()
    real=is_real_person(fromv)
    # categories first
    financial_kw=['bank','statement','invoice','payment','paid','bill','billing','receipt','charge','transaction','deposit','withdrawal','venmo','paypal','zelle','credit card','mortgage','loan','insurance','tax','irs','wealthfront','vanguard','fidelity','chase','bank of america','boa','capital one','amex','american express','eversource','national grid','water and sewer','autopay']
    shopping_kw=['order','shipped','shipping','delivered','delivery','out for delivery','your package','tracking','purchase','return','refund','amazon','target','instacart','doordash','uber eats','etsy','shop','receipt']
    newsletter_kw=['unsubscribe','newsletter','digest','sale','% off','promotion','promo','marketing','weekly','daily brief','roundup','substack','campaign','deal','advertisement']
    social_kw=['facebook','instagram','linkedin','twitter','x.com','threads','tiktok','friend request','mentioned you','tagged you','invited you','event invite']
    unexpected_fin=['failed','declined','past due','overdue','unknown','suspicious','fraud','verify','compromise','unauthorized','action required']
    if any(k in text for k in financial_kw):
        label='Financial'
        surface=any(k in text for k in unexpected_fin)
        if surface and not real: return ('Urgent', True)
        return (label, False)
    if any(k in text for k in shopping_kw): return ('Shopping', False)
    if any(k in text for k in social_kw): return ('Social', False)
    if any(k in text for k in newsletter_kw): return ('Newsletters', False)
    if real:
        urgent_terms=['urgent','asap','today','tonight','this morning','this afternoon','deadline','appointment','time-sensitive','running late','can you call','need by']
        action_terms=['can you','could you','please','would you','let me know','rsvp','respond','reply','confirm','question','?','are you able','do you want','can we','would love','please send']
        if any(k in text for k in urgent_terms): return ('Urgent', True)
        if any(k in text for k in action_terms): return ('Action', True)
        return ('FYI', True)
    return ('Newsletters', False)

def maybe_draft_body(fromv, subj, snippet, body):
    # Conservative: only draft simple holding replies to real-person action messages.
    text=(body or snippet or '').strip()
    if not text: return None
    name=display_name(fromv).split()[0]
    return f"Hi {name},\n\nThanks for reaching out — I'll take a look and get back to you shortly.\n\nBest,\nJulia"

def raw_email(to, subj, msgid, body):
    subject = subj if subj.lower().startswith('re:') else 'Re: '+subj
    headers=[f'To: {to}', f'Subject: {subject}']
    if msgid:
        headers += [f'In-Reply-To: {msgid}', f'References: {msgid}']
    headers += ['Content-Type: text/plain; charset=utf-8', '', body]
    s='\r\n'.join(headers)
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')

def summarize_calendar(resp):
    items=[]
    if isinstance(resp, dict): items=resp.get('items') or []
    elif isinstance(resp, list): items=resp
    out=[]
    for ev in items:
        title=ev.get('summary') or '(untitled)'
        loc=ev.get('location')
        start=ev.get('start') or {}; end=ev.get('end') or {}
        if 'date' in start:
            desc=f'all-day: {title}'
        else:
            s=start.get('dateTime','')
            e=end.get('dateTime','')
            def fmt(x):
                if not x: return ''
                # fromisoformat handles offsets
                d=dt.datetime.fromisoformat(x.replace('Z','+00:00'))
                local=d.astimezone(dt.timezone(dt.timedelta(hours=-4)))
                return local.strftime('%-I:%M %p').replace(':00','')
            desc=f"{fmt(s)}: {title}"
            if e:
                desc=f"{fmt(s)}–{fmt(e)}: {title}"
        if loc: desc+=f" ({loc})"
        out.append(desc)
    return out

def parse_sleep(txt):
    if not txt or 'No sleep data available' in txt or 'error' in txt.lower(): return None
    # Keep output concise; extract score/duration/rem/deep if present.
    score=re.search(r'(?:score|sleep score)\D{0,10}(\d{1,3})', txt, re.I)
    dur=re.search(r'(?:duration|asleep|time asleep)\D{0,20}([0-9]+h(?:\s*[0-9]+m)?|[0-9]+:[0-9]{2})', txt, re.I)
    rem=re.search(r'REM\D{0,10}(\d{1,3})\s*%', txt, re.I)
    deep=re.search(r'Deep\D{0,10}(\d{1,3})\s*%', txt, re.I)
    parts=[]
    if score: parts.append(f"score {score.group(1)}")
    if dur: parts.append(f"{dur.group(1)} asleep")
    if rem: parts.append(f"REM {rem.group(1)}%")
    if deep: parts.append(f"deep {deep.group(1)}%")
    return ', '.join(parts) if parts else txt.strip().splitlines()[0][:160]

summary={'calendar': [], 'sleep': None, 'unread_count':0, 'urgent':[], 'action':[], 'fyi':[], 'drafts':0, 'archived':0, 'trashed':0, 'labeled':{}, 'errors':[]}

cal=gws(['calendar','events','list'], {'calendarId':'primary','timeMin':TODAY+'T00:00:00'+OFFSET,'timeMax':TOMORROW+'T00:00:00'+OFFSET,'singleEvents':True,'orderBy':'startTime'})
summary['calendar']=summarize_calendar(cal)

p=run(['8sleep','sleep','julia'], check=False)
if p.returncode==0:
    summary['sleep']=parse_sleep(p.stdout)

labels_resp=gws(['gmail','users','labels','list'], {'userId':'me'})
labels=as_list_labels(labels_resp)
by_name={l.get('name'):l for l in labels if isinstance(l,dict)}
for name in FULL_LABELS:
    if name not in by_name:
        created=gws(['gmail','users','labels','create'], {'userId':'me'}, {'name':name,'labelListVisibility':'labelShow','messageListVisibility':'show'})
        if isinstance(created,dict): by_name[name]=created
# refresh if any missing ID
if not all(name in by_name and by_name[name].get('id') for name in FULL_LABELS):
    labels=as_list_labels(gws(['gmail','users','labels','list'], {'userId':'me'}))
    by_name={l.get('name'):l for l in labels if isinstance(l,dict)}
label_ids={name.split('/')[-1]:by_name[name]['id'] for name in FULL_LABELS if name in by_name and by_name[name].get('id')}

unread=messages_from(gws(['gmail','users','messages','list'], {'userId':'me','q':'is:unread in:inbox','maxResults':50}))
summary['unread_count']=len(unread)
for m in unread:
    mid=m.get('id')
    if not mid: continue
    msg=gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':'full'})
    h=hdrs(msg)
    fromv=h.get('from','')
    subj=h.get('subject','(no subject)')
    snippet=msg.get('snippet','') if isinstance(msg,dict) else ''
    body=decode_body((msg or {}).get('payload') or {})
    label, surface=classify(fromv, subj, snippet, body)
    lid=label_ids.get(label)
    if lid:
        gws(['gmail','users','messages','modify'], {'userId':'me','id':mid}, {'addLabelIds':[lid]})
        summary['labeled'][label]=summary['labeled'].get(label,0)+1
    who=display_name(fromv)
    item=f"{who}: {subj}"
    if label=='Urgent':
        gws(['gmail','users','messages','modify'], {'userId':'me','id':mid}, {'addLabelIds':['STARRED']})
        summary['urgent'].append(item)
    elif label=='Action' and is_real_person(fromv):
        summary['action'].append(item)
        msgid=h.get('message-id','')
        sender=email_addr(fromv) or fromv
        draft=maybe_draft_body(fromv, subj, snippet, body)
        if draft:
            raw=raw_email(sender, subj, msgid, draft)
            try:
                gws(['gmail','users','drafts','create'], {'userId':'me'}, {'message':{'threadId':msg.get('threadId'), 'raw':raw}})
                summary['drafts']+=1
            except Exception as e:
                summary['errors'].append('draft failed for '+mid)
    elif label=='FYI' and surface:
        summary['fyi'].append(item)

old=messages_from(gws(['gmail','users','messages','list'], {'userId':'me','q':'is:read in:inbox older_than:1d','maxResults':50}))
urgent_id=label_ids.get('Urgent'); action_id=label_ids.get('Action')
for m in old:
    mid=m.get('id')
    if not mid: continue
    msg=gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':'full'})
    lids=set(msg.get('labelIds') or [])
    if 'STARRED' in lids or (urgent_id and urgent_id in lids) or (action_id and action_id in lids):
        continue
    gws(['gmail','users','messages','modify'], {'userId':'me','id':mid}, {'removeLabelIds':['INBOX']})
    summary['archived']+=1

promos=messages_from(gws(['gmail','users','messages','list'], {'userId':'me','q':'in:inbox category:promotions is:unread older_than:3d','maxResults':20}))
spam_terms=['offer','sale','discount','promo','promotion','deal','% off','unsubscribe','limited time','clearance','ends today','newsletter']
for m in promos:
    mid=m.get('id')
    if not mid: continue
    msg=gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':'full'})
    h=hdrs(msg); text=(h.get('from','')+' '+h.get('subject','')+' '+msg.get('snippet','')).lower()
    if any(t in text for t in spam_terms) and not is_real_person(h.get('from','')):
        gws(['gmail','users','messages','trash'], {'userId':'me','id':mid})
        summary['trashed']+=1

# Compose briefing
lines=[]
lines.append('Good morning Julia! Happy Monday.')
if summary['calendar']:
    lines.append('')
    lines.append('Calendar: ' + '; '.join(summary['calendar']) + '.')
else:
    lines.append('')
    lines.append('Calendar: nothing scheduled today.')
if summary['sleep']:
    lines.append('')
    lines.append('Sleep: ' + summary['sleep'] + '.')
email_bits=[]
if summary['urgent']:
    email_bits.append('Urgent: ' + '; '.join(summary['urgent'][:5]))
if summary['action']:
    email_bits.append('Action: ' + '; '.join(summary['action'][:5]) + (f" — drafted {summary['drafts']} repl{'y' if summary['drafts']==1 else 'ies'}, check your drafts." if summary['drafts'] else ''))
if summary['fyi']:
    email_bits.append('FYI: ' + '; '.join(summary['fyi'][:5]))
if not email_bits:
    email_bits.append('No urgent or personal action emails in the unread inbox.')
lines.append('')
lines.append('Email: ' + ' '.join(email_bits))
lines.append('')
lines.append(f"Cleanup: archived {summary['archived']} old email{'s' if summary['archived']!=1 else ''}, trashed {summary['trashed']} spam.")
lines.append('')
lines.append('Have a great day!')
summary['briefing']='\n'.join(lines)
open('/Users/dbochman/.openclaw/workspace/tmp/julia_morning_summary.json','w').write(json.dumps(summary, indent=2))
print(summary['briefing'])
