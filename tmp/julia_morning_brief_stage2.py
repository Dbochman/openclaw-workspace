import base64, datetime as dt, json, os, re, subprocess
from email.utils import parseaddr
ACCOUNT='julia.joy.jennings@gmail.com'; TODAY='2026-06-22'; TOMORROW='2026-06-23'; OFFSET='-04:00'
REQ_LABELS=['Urgent','Action','FYI','Financial','Shopping','Newsletters','Social']; FULL_LABELS=[f'OpenClaw/{x}' for x in REQ_LABELS]
def run(cmd, check=True):
 p=subprocess.run(cmd,capture_output=True,text=True)
 if check and p.returncode: raise RuntimeError((p.stderr or '')+(p.stdout or ''))
 return p
def gws(args, params=None, body=None, check=True):
 cmd=['gws']+args
 if params is not None: cmd += ['--params', json.dumps(params,separators=(',',':'))]
 if body is not None: cmd += ['--json', json.dumps(body,separators=(',',':'))]
 cmd += ['--account',ACCOUNT]
 p=run(cmd,check=check); out=p.stdout.strip()
 if not out: return None
 try: return json.loads(out)
 except: return out
def msgs(resp): return (resp or {}).get('messages') or ([] if not isinstance(resp,list) else resp)
def labs(resp): return (resp or {}).get('labels') or ([] if not isinstance(resp,list) else resp)
def hdrs(msg):
 d={}
 for h in (((msg or {}).get('payload') or {}).get('headers') or []):
  n=h.get('name','').lower()
  if n and n not in d: d[n]=h.get('value','')
 return d
def parseaddr_l(s): return parseaddr(s)[1].lower()
def dname(s):
 n,a=parseaddr(s); return (n.replace('"','').strip() or (a.split('@')[0] if a else s))
auto=['no-reply','noreply','donotreply','do-not-reply','notification','notifications','marketing','newsletter','offers','promo','support','alerts','billing','statement','receipt']
def real(fromv):
 a=parseaddr_l(fromv); local=a.split('@')[0] if '@' in a else a; dom=a.split('@')[-1] if '@' in a else ''; name=dname(fromv).lower()
 if any(t in local for t in auto) or any(t in name for t in ['noreply','no reply','notification','newsletter','team','support','service','billing']): return False
 if dom in ['facebookmail.com','instagram.com','linkedin.com','twitter.com','x.com','tiktok.com','mailchimpapp.net','substack.com','medium.com','spotify.com','amazon.com','google.com']: return False
 return bool(a)
def body_text(payload):
 out=[]
 def rec(p):
  mime=p.get('mimeType',''); data=(p.get('body') or {}).get('data')
  if data and (mime.startswith('text/plain') or mime.startswith('text/html')):
   try:
    s=base64.urlsafe_b64decode(data+'='*((4-len(data)%4)%4)).decode('utf-8','ignore')
    if mime.startswith('text/html'):
     s=re.sub(r'<(br|p|div|li|tr)[^>]*>','\n',s,flags=re.I); s=re.sub(r'<[^>]+>','',s); s=s.replace('&nbsp;',' ').replace('&amp;','&')
    out.append(s)
   except: pass
  for c in p.get('parts') or []: rec(c)
 rec(payload or {}); return '\n'.join(out).strip()
def classify(fromv,subj,snip,body):
 text=' '.join([fromv,subj,snip or '',body[:1000] if body else '']).lower(); r=real(fromv)
 financial=['bank','statement','invoice','payment','paid','bill','billing','receipt','charge','transaction','deposit','withdrawal','venmo','paypal','zelle','credit card','mortgage','loan','insurance','tax','irs','wealthfront','vanguard','fidelity','chase','bank of america','capital one','amex','eversource','national grid','autopay']
 shopping=['order','shipped','shipping','delivered','delivery','out for delivery','your package','tracking','purchase','return','refund','amazon','target','instacart','doordash','uber eats','etsy','shop','receipt']
 social=['facebook','instagram','linkedin','twitter','x.com','threads','tiktok','friend request','mentioned you','tagged you','invited you','event invite']
 news=['unsubscribe','newsletter','digest','sale','% off','promotion','promo','marketing','weekly','roundup','substack','campaign','deal','advertisement']
 unexpected=['failed','declined','past due','overdue','unknown','suspicious','fraud','verify','compromise','unauthorized','action required']
 if any(k in text for k in financial): return ('Urgent' if any(k in text for k in unexpected) and not r else 'Financial')
 if any(k in text for k in shopping): return 'Shopping'
 if any(k in text for k in social): return 'Social'
 if any(k in text for k in news): return 'Newsletters'
 if r:
  if any(k in text for k in ['urgent','asap','today','tonight','this morning','deadline','appointment','time-sensitive','running late']): return 'Urgent'
  if any(k in text for k in ['can you','could you','please','would you','let me know','rsvp','respond','reply','confirm','question','?','are you able','do you want','can we','would love','please send']): return 'Action'
  return 'FYI'
 return 'Newsletters'
def raw(to,subj,msgid,body):
 subject=subj if subj.lower().startswith('re:') else 'Re: '+subj
 lines=[f'To: {to}',f'Subject: {subject}']
 if msgid: lines += [f'In-Reply-To: {msgid}',f'References: {msgid}']
 lines += ['Content-Type: text/plain; charset=utf-8','',body]
 return base64.urlsafe_b64encode('\r\n'.join(lines).encode()).decode().rstrip('=')
def cal_summary(resp):
 items=(resp or {}).get('items') or ([] if not isinstance(resp,list) else resp); out=[]
 for ev in items:
  title=ev.get('summary') or '(untitled)'; loc=ev.get('location'); st=ev.get('start') or {}; en=ev.get('end') or {}
  if 'date' in st: desc=f'all-day: {title}'
  else:
   def fmt(x):
    d=dt.datetime.fromisoformat(x.replace('Z','+00:00')); d=d.astimezone(dt.timezone(dt.timedelta(hours=-4))); return d.strftime('%-I:%M %p').replace(':00','')
   desc=f"{fmt(st.get('dateTime',''))}–{fmt(en.get('dateTime',''))}: {title}" if en.get('dateTime') else f"{fmt(st.get('dateTime',''))}: {title}"
  if loc: desc += f' ({loc})'
  out.append(desc)
 return out
def sleep_summary(txt):
 if not txt or 'No sleep data available' in txt or 'error' in txt.lower(): return None
 score=re.search(r'(?:score|sleep score)\D{0,10}(\d{1,3})',txt,re.I); dur=re.search(r'(?:duration|asleep|time asleep)\D{0,20}([0-9]+h(?:\s*[0-9]+m)?|[0-9]+:[0-9]{2})',txt,re.I); rem=re.search(r'REM\D{0,10}(\d{1,3})\s*%',txt,re.I); deep=re.search(r'Deep\D{0,10}(\d{1,3})\s*%',txt,re.I)
 parts=[]
 if score: parts.append(f'score {score.group(1)}')
 if dur: parts.append(f'{dur.group(1)} asleep')
 if rem: parts.append(f'REM {rem.group(1)}%')
 if deep: parts.append(f'deep {deep.group(1)}%')
 return ', '.join(parts) if parts else txt.strip().splitlines()[0][:160]
summary={'calendar':cal_summary(gws(['calendar','events','list'],{'calendarId':'primary','timeMin':TODAY+'T00:00:00'+OFFSET,'timeMax':TOMORROW+'T00:00:00'+OFFSET,'singleEvents':True,'orderBy':'startTime'})), 'sleep':None,'urgent':[],'action':[],'fyi':[],'drafts_created':0,'drafts_present':0,'archived':0,'trashed':0,'label_counts':{}}
p=run(['8sleep','sleep','julia'],check=False)
if p.returncode==0: summary['sleep']=sleep_summary(p.stdout)
by={l.get('name'):l for l in labs(gws(['gmail','users','labels','list'],{'userId':'me'})) if isinstance(l,dict)}
for name in FULL_LABELS:
 if name not in by:
  c=gws(['gmail','users','labels','create'],{'userId':'me'},{'name':name,'labelListVisibility':'labelShow','messageListVisibility':'show'})
  if isinstance(c,dict): by[name]=c
by={l.get('name'):l for l in labs(gws(['gmail','users','labels','list'],{'userId':'me'})) if isinstance(l,dict)}
lid={n.split('/')[-1]:by[n]['id'] for n in FULL_LABELS if n in by}
# existing draft threads
existing_draft_threads=set()
dr=gws(['gmail','users','drafts','list'],{'userId':'me','maxResults':100},check=False)
if isinstance(dr,dict):
 for d in dr.get('drafts') or []:
  try:
   gd=gws(['gmail','users','drafts','get'],{'userId':'me','id':d.get('id'),'format':'metadata'},check=False)
   if isinstance(gd,dict) and gd.get('message',{}).get('threadId'): existing_draft_threads.add(gd['message']['threadId'])
  except: pass
unread=msgs(gws(['gmail','users','messages','list'],{'userId':'me','q':'is:unread in:inbox','maxResults':50}))
for m in unread:
 mid=m.get('id'); msg=gws(['gmail','users','messages','get'],{'userId':'me','id':mid,'format':'full'}); h=hdrs(msg); fromv=h.get('from',''); subj=h.get('subject','(no subject)'); bt=body_text((msg or {}).get('payload') or {}); label=classify(fromv,subj,msg.get('snippet',''),bt)
 if lid.get(label):
  gws(['gmail','users','messages','modify'],{'userId':'me','id':mid},{'addLabelIds':[lid[label]]})
  summary['label_counts'][label]=summary['label_counts'].get(label,0)+1
 item=f"{dname(fromv)}: {subj}"
 if label=='Urgent':
  gws(['gmail','users','messages','modify'],{'userId':'me','id':mid},{'addLabelIds':['STARRED']}); summary['urgent'].append(item)
 elif label=='Action' and real(fromv):
  summary['action'].append(item); th=msg.get('threadId')
  if th in existing_draft_threads: summary['drafts_present']+=1
  else:
   sender=parseaddr_l(fromv) or fromv; name=dname(fromv).split()[0]; body=f"Hi {name},\n\nThanks for reaching out — I'll take a look and get back to you shortly.\n\nBest,\nJulia"
   gws(['gmail','users','drafts','create'],{'userId':'me'},{'message':{'threadId':th,'raw':raw(sender,subj,h.get('message-id',''),body)}}); summary['drafts_created']+=1; existing_draft_threads.add(th)
 elif label=='FYI' and real(fromv): summary['fyi'].append(item)
old=msgs(gws(['gmail','users','messages','list'],{'userId':'me','q':'is:read in:inbox older_than:1d','maxResults':50}))
for m in old:
 mid=m.get('id'); msg=gws(['gmail','users','messages','get'],{'userId':'me','id':mid,'format':'full'}); labels=set(msg.get('labelIds') or [])
 if 'STARRED' in labels or lid.get('Urgent') in labels or lid.get('Action') in labels: continue
 gws(['gmail','users','messages','modify'],{'userId':'me','id':mid},{'removeLabelIds':['INBOX']}); summary['archived']+=1
promos=msgs(gws(['gmail','users','messages','list'],{'userId':'me','q':'in:inbox category:promotions is:unread older_than:3d','maxResults':20}))
for m in promos:
 mid=m.get('id'); msg=gws(['gmail','users','messages','get'],{'userId':'me','id':mid,'format':'full'}); h=hdrs(msg); text=(h.get('from','')+' '+h.get('subject','')+' '+msg.get('snippet','')).lower()
 if (not real(h.get('from',''))) and any(t in text for t in ['offer','sale','discount','promo','promotion','deal','% off','unsubscribe','limited time','clearance','ends today','newsletter']):
  # gws trash endpoint is buggy on this install (Google 411), so move to Trash via labels.
  gws(['gmail','users','messages','modify'],{'userId':'me','id':mid},{'addLabelIds':['TRASH'],'removeLabelIds':['INBOX']})
  summary['trashed']+=1
lines=['Good morning Julia! Happy Monday.','']
lines.append('Calendar: '+('; '.join(summary['calendar'])+'.' if summary['calendar'] else 'nothing scheduled today.'))
if summary['sleep']:
 lines += ['', 'Sleep: '+summary['sleep']+'.']
bits=[]
if summary['urgent']: bits.append('Urgent: '+'; '.join(summary['urgent'][:5]))
if summary['action']:
 d=summary['drafts_created']+summary['drafts_present']; suffix=(f" — drafted repl{'y' if d==1 else 'ies'} are in drafts." if d else '')
 bits.append('Action: '+'; '.join(summary['action'][:5])+suffix)
if summary['fyi']: bits.append('FYI: '+'; '.join(summary['fyi'][:5]))
if not bits: bits.append('No urgent or personal action emails in the unread inbox.')
lines += ['', 'Email: '+' '.join(bits), '', f"Cleanup: archived {summary['archived']} old email{'s' if summary['archived']!=1 else ''} this pass, trashed {summary['trashed']} spam.", '', 'Have a great day!']
summary['briefing']='\n'.join(lines)
open('/Users/dbochman/.openclaw/workspace/tmp/julia_morning_summary.json','w').write(json.dumps(summary,indent=2))
print(summary['briefing'])
