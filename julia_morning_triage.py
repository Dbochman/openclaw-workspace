import base64
import email.utils
import html
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict

ACCOUNT = 'julia.joy.jennings@gmail.com'
DATE = '2026-06-26'
LABEL_NAMES = [
    'OpenClaw/Urgent', 'OpenClaw/Action', 'OpenClaw/FYI', 'OpenClaw/Financial',
    'OpenClaw/Shopping', 'OpenClaw/Newsletters', 'OpenClaw/Social'
]
PRIMARY_ORDER = ['Urgent','Action','FYI','Financial','Shopping','Newsletters','Social']
PRIMARY_LABELS = {k: f'OpenClaw/{k}' for k in PRIMARY_ORDER}
RESULT = {
    'schemaVersion': 1,
    'status': 'ok',
    'date': DATE,
    'processed': 0,
    'markedRead': 0,
    'leftUnread': 0,
    'draftsCreated': 0,
    'draftsExisting': 0,
    'archived': 0,
    'trashed': 0,
    'unreadAfter': [],
    'attention': [],
    'errors': []
}

def emit():
    print(json.dumps(RESULT, ensure_ascii=False, separators=(',', ':')))

os.environ['GOOGLE_WORKSPACE_CLI_ACCOUNT'] = ACCOUNT

def run_gws(parts, params=None, body=None, timeout=120, retry_auth=True):
    # Every Gmail call includes params with userId=me as required.
    params = dict(params or {})
    params.setdefault('userId', 'me')
    cmd = ['gws'] + parts + ['--params', json.dumps(params, separators=(',', ':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body, separators=(',', ':'))]
    cmd += ['--account', ACCOUNT]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or '').strip()
    err = (p.stderr or '').strip()
    if p.returncode != 0:
        combined = (out + '\n' + err).strip()
        if retry_auth and ('auth' in combined.lower() or 'credentials' in combined.lower() or 'token' in combined.lower()):
            time.sleep(5)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = (p.stdout or '').strip()
            err = (p.stderr or '').strip()
        if p.returncode != 0:
            raise RuntimeError(((out + '\n' + err).strip() or 'gws command failed')[:500])
    if not out:
        return {}
    try:
        return json.loads(out)
    except Exception as e:
        raise RuntimeError(f'Invalid JSON from gws: {e}')

def list_all_messages(q):
    ids = []
    token = None
    while True:
        params = {'userId':'me', 'q': q, 'maxResults': 100}
        if token:
            params['pageToken'] = token
        data = run_gws(['gmail','users','messages','list'], params=params)
        ids.extend([m['id'] for m in data.get('messages', []) if 'id' in m])
        token = data.get('nextPageToken')
        if not token:
            return ids

def list_all_drafts():
    drafts = []
    token = None
    while True:
        params = {'userId':'me', 'maxResults':100}
        if token:
            params['pageToken'] = token
        data = run_gws(['gmail','users','drafts','list'], params=params)
        drafts.extend(data.get('drafts', []) or [])
        token = data.get('nextPageToken')
        if not token:
            return drafts

def get_msg(mid, fmt='full'):
    return run_gws(['gmail','users','messages','get'], params={'userId':'me','id':mid,'format':fmt})

def get_thread(tid):
    return run_gws(['gmail','users','threads','get'], params={'userId':'me','id':tid,'format':'full'})

def headers(msg):
    return {h.get('name','').lower(): h.get('value','') for h in msg.get('payload',{}).get('headers',[]) or []}

def decode_part_data(data):
    if not data:
        return ''
    try:
        pad = '=' * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + pad).encode()).decode('utf-8', 'replace')
    except Exception:
        return ''

def body_text(payload):
    texts=[]
    def walk(part):
        mt = part.get('mimeType','')
        body = part.get('body',{}) or {}
        if mt in ('text/plain','text/html') and body.get('data'):
            txt = decode_part_data(body.get('data'))
            if mt == 'text/html':
                txt = re.sub(r'<(script|style).*?</\1>', ' ', txt, flags=re.I|re.S)
                txt = re.sub(r'<[^>]+>', ' ', txt)
                txt = html.unescape(txt)
            texts.append(txt)
        for child in part.get('parts',[]) or []:
            walk(child)
    walk(payload or {})
    return re.sub(r'\s+', ' ', '\n'.join(texts)).strip()

def batch_modify(ids, add=None, remove=None):
    if not ids:
        return
    add = add or []
    remove = remove or []
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i+1000]
        body = {'ids': chunk}
        if add:
            body['addLabelIds'] = add
        if remove:
            body['removeLabelIds'] = remove
        run_gws(['gmail','users','messages','batchModify'], params={'userId':'me'}, body=body, timeout=180)

def create_label(name):
    return run_gws(['gmail','users','labels','create'], params={'userId':'me'}, body={
        'name': name,
        'labelListVisibility': 'labelShow',
        'messageListVisibility': 'show'
    })

def create_draft(raw_b64, thread_id):
    return run_gws(['gmail','users','drafts','create'], params={'userId':'me'}, body={'message': {'raw': raw_b64, 'threadId': thread_id}}, timeout=120)

def classify(h, snippet, text):
    frm = h.get('from','')
    subj = h.get('subject','')
    low = (frm + ' ' + subj + ' ' + snippet + ' ' + text[:2000]).lower()
    dom = (email.utils.parseaddr(frm)[1].split('@')[-1] if '@' in email.utils.parseaddr(frm)[1] else '').lower()
    # Urgent / unexpected failures.
    urgent_terms = ['payment failed','failed payment','account suspended','security alert','unauthorized','fraud','past due','overdue','action required today','expires today','deadline today','appointment today','reset your password']
    if any(t in low for t in urgent_terms) and not any(t in low for t in ['newsletter','daily headlines','job alert']):
        return 'Urgent', 'unexpected time-sensitive account/security/financial issue'
    # Shopping/order lifecycle.
    shopping_domains = ['amazon.com','wallcontrol.com','wallcontrol.info','stamped.io','shop.app','ups.com','fedex.com','usps.com']
    shopping_terms = ['order','delivered','shipment','shipping','on the way','receipt','invoice','purchase','feedback','review your purchase','track your shipment','return']
    if any(d in dom for d in shopping_domains) or any(t in low for t in shopping_terms):
        # Avoid retirement/utility bill statements being pulled by generic invoice wording later.
        if 't. rowe price' not in low and 'betterment' not in low and 'national grid' not in low:
            return 'Shopping', 'routine order, receipt, shipping, or purchase-related update'
    # Financial expected mail.
    financial_domains = ['nationalgridus.com','betterment.com','troweprice.com','fidelity.com','vanguard.com','bankofamerica.com','chase.com','americanexpress.com','capitalone.com','venmo.com','paypal.com']
    financial_terms = ['bill','statement','deposit','payment','bank','credit card','retirement','investing','transaction','portfolio','dividend','transfer']
    if any(d in dom for d in financial_domains) or any(t in low for t in financial_terms):
        # Marketing/insights/job-alert-like financial brand content goes to newsletters.
        if any(t in low for t in ['insights','webinar','ways to','explore ways','newsletter','market commentary']) and not any(t in low for t in ['bill','statement','payment due','deposit is happening','transaction']):
            return 'Newsletters', 'financial-brand newsletter or marketing content'
        return 'Financial', 'routine bill, statement, deposit, payment, or financial notice'
    # Social/calendar/event notifications.
    social_domains = ['linkedin.com','facebookmail.com','instagram.com','eventbrite.com','calendar.google.com']
    if any(d in dom for d in social_domains) or any(t in low for t in ['invitation','invited you','event update','calendar invitation']):
        # Job alerts are newsletters per instructions.
        if 'job alert' in low or 'jobalerts' in low:
            return 'Newsletters', 'job alert subscription'
        return 'Social', 'social or event notification'
    # Action/reply needed: direct human mail with clear asks, excluding no-reply/bulk.
    addr = email.utils.parseaddr(frm)[1].lower()
    bulkish = any(x in addr for x in ['no-reply','noreply','newsletter','notification','alerts','marketing','support@','hello@','info@','updates@','daily.','jobalerts']) or h.get('list-unsubscribe')
    ask_terms = ['can you','could you','please','would you','let me know','rsvp','confirm','are you able','do you want','question']
    if not bulkish and any(t in low for t in ask_terms):
        return 'Action', 'direct request appears to need Julia reply or action'
    # Newsletters/promotions/digests/alerts.
    newsletter_terms = ['unsubscribe','view in browser','newsletter','digest','promotion','sale','daily headlines','google alert','job alert','read more','save the date','marketing']
    if h.get('list-unsubscribe') or any(t in low for t in newsletter_terms) or 'category_promotions' in ' '.join(h.get('labelids','')):
        return 'Newsletters', 'newsletter, digest, marketing, promotion, or alert'
    # Real person FYI fallback; automated fallback newsletters.
    if not bulkish:
        return 'FYI', 'informational mail from a person with no clear response needed'
    return 'Newsletters', 'automated informational or promotional mail'

def obvious_spam(h, snippet, text):
    frm = h.get('from','')
    subj = h.get('subject','')
    low = (frm+' '+subj+' '+snippet+' '+text[:1000]).lower()
    protected = ['receipt','order','statement','bill','bank','payment','security','account','appointment','medical','doctor','travel','flight','hotel','legal','invoice','shipment','delivered','subscription']
    if any(p in low for p in protected):
        return False
    spam_terms = ['final reminder: complete your order','limited time offer','sale ends','deal ends','act now','clearance','promo code','exclusive offer']
    return bool(any(t in low for t in spam_terms) and (h.get('list-unsubscribe') or 'category_promotions' in low))

try:
    # Auth check already run by caller; do a quick guarded auth dependency check here too.
    run_gws(['gmail','users','messages','list'], params={'userId':'me','q':'is:unread in:inbox','maxResults':1})
except Exception as e:
    time.sleep(5)
    try:
        run_gws(['gmail','users','messages','list'], params={'userId':'me','q':'is:unread in:inbox','maxResults':1}, retry_auth=False)
    except Exception as e2:
        RESULT['status'] = 'auth_error'
        RESULT['errors'] = [{'stage':'auth','message':'Gmail authentication failed'}]
        emit(); sys.exit(0)

try:
    # 1. Ensure labels.
    lab_data = run_gws(['gmail','users','labels','list'], params={'userId':'me'})
    labels = {l.get('name'): l.get('id') for l in lab_data.get('labels', [])}
    for name in LABEL_NAMES:
        if name not in labels:
            made = create_label(name)
            labels[made.get('name', name)] = made.get('id')
    # Refresh map to be safe.
    lab_data = run_gws(['gmail','users','labels','list'], params={'userId':'me'})
    labels = {l.get('name'): l.get('id') for l in lab_data.get('labels', [])}
    primary_ids = [labels[n] for n in LABEL_NAMES if labels.get(n)]
    cls_to_id = {k: labels[v] for k,v in PRIMARY_LABELS.items()}
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'labels','message':str(e)[:180]})
    emit(); sys.exit(0)

# 2. Remove clear spam.
try:
    spam_ids = list_all_messages('in:inbox category:promotions is:unread older_than:3d')
    trash_ids = []
    for mid in spam_ids:
        try:
            m = get_msg(mid, 'full')
            h = headers(m)
            text = body_text(m.get('payload',{}))
            # Gmail headers do not include labels; include label ids in the low-text check.
            h['labelids'] = ' '.join(m.get('labelIds',[]))
            if obvious_spam(h, m.get('snippet',''), text):
                trash_ids.append(mid)
        except Exception as e:
            RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'spam_fetch','messageId':mid,'message':str(e)[:160]})
    if trash_ids:
        batch_modify(trash_ids, add=['TRASH'], remove=['INBOX','UNREAD'])
        RESULT['trashed'] = len(trash_ids)
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'spam','message':str(e)[:180]})

# 3. Triage unread inbox.
processed_infos = []
try:
    unread_ids = list_all_messages('is:unread in:inbox')
    for mid in unread_ids:
        try:
            m = get_msg(mid, 'full')
            h = headers(m)
            h['labelids'] = ' '.join(m.get('labelIds',[]))
            text = body_text(m.get('payload',{}))
            cls, reason = classify(h, m.get('snippet',''), text)
            processed_infos.append({'id':mid,'threadId':m.get('threadId'),'headers':h,'labels':m.get('labelIds',[]),'class':cls,'reason':reason,'text':text,'snippet':m.get('snippet','')})
            RESULT['processed'] += 1
        except Exception as e:
            RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'fetch_classify','messageId':mid,'message':str(e)[:160]})
    # Apply label changes in batches with identical add/remove sets.
    groups = defaultdict(list)
    for info in processed_infos:
        stale_urgent = cls_to_id.get('Urgent') in info['labels'] and info['class'] != 'Urgent'
        remove = set(primary_ids)
        if info['class'] != 'Urgent':
            # Remove stale attention only if it was previously OpenClaw/Urgent.
            if stale_urgent:
                remove.add('STARRED')
        add = {cls_to_id[info['class']]}
        if info['class'] == 'Urgent':
            add.add('STARRED')
        groups[(tuple(sorted(add)), tuple(sorted(remove)))].append(info['id'])
    for (add, remove), ids in groups.items():
        try:
            batch_modify(ids, add=list(add), remove=list(remove))
        except Exception as e:
            RESULT['status'] = 'partial'
            for mid in ids:
                RESULT['errors'].append({'stage':'label','messageId':mid,'message':str(e)[:140]})
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'triage','message':str(e)[:180]})

# 4. Thread-aware drafts for Action messages.
# Current run has no expected direct Action messages, but support the rule if one appears.
try:
    action_infos = [i for i in processed_infos if i['class'] == 'Action']
    draft_threads = set()
    if action_infos:
        for d in list_all_drafts():
            tid = ((d.get('message') or {}).get('threadId'))
            if tid: draft_threads.add(tid)
    for info in action_infos:
        mid = info['id']; tid = info['threadId']; h = info['headers']
        try:
            if tid in draft_threads:
                RESULT['draftsExisting'] += 1
                RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':'Existing reply draft needs Julia review','deadline':'','draftStatus':'existing'})
                continue
            th = get_thread(tid)
            msgs = th.get('messages',[]) or []
            # If Julia has already replied after this message, downgrade to FYI.
            julia_after = False
            latest_non_draft = None
            for tm in msgs:
                thh = headers(tm)
                if 'DRAFT' not in tm.get('labelIds',[]):
                    latest_non_draft = tm
                if tm.get('internalDate','0') > next((x.get('internalDate','0') for x in msgs if x.get('id')==mid), '0'):
                    addr = email.utils.parseaddr(thh.get('from',''))[1].lower()
                    if addr == ACCOUNT:
                        julia_after = True
            if julia_after or (latest_non_draft and latest_non_draft.get('id') != mid):
                # Downgrade to FYI/read unless other action remains.
                batch_modify([mid], add=[cls_to_id['FYI']], remove=primary_ids + ['UNREAD'])
                RESULT['markedRead'] += 1
                info['read_done'] = True
                continue
            to_addr = email.utils.parseaddr(h.get('reply-to') or h.get('from',''))[1]
            if not to_addr:
                RESULT['leftUnread'] += 1
                RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':'Direct action appears needed, but no reply address was available','deadline':'','draftStatus':'none'})
                continue
            subj = h.get('subject','')
            if not subj.lower().startswith('re:'):
                subj = 'Re: ' + subj
            from email.message import EmailMessage
            em = EmailMessage()
            em['To'] = to_addr
            em['Subject'] = subj
            em['In-Reply-To'] = h.get('message-id','')
            refs = (h.get('references','') + ' ' + h.get('message-id','')).strip()
            if refs: em['References'] = refs
            name = email.utils.parseaddr(h.get('from',''))[0].split()[0] or 'there'
            em.set_content(f"Hi {name},\n\nThanks for reaching out. I’ll take a look and get back to you soon.\n\nBest,\nJulia\n")
            raw = base64.urlsafe_b64encode(em.as_bytes()).decode().rstrip('=')
            create_draft(raw, tid)
            RESULT['draftsCreated'] += 1
            RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':'Reply draft needs Julia review','deadline':'','draftStatus':'created'})
        except Exception as e:
            RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'draft','messageId':mid,'message':str(e)[:160]})
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'drafts','message':str(e)[:180]})

# 5. Resolve read state and attention.
try:
    keep_unread = set()
    for info in processed_infos:
        if info.get('read_done'):
            continue
        cls = info['class']; h = info['headers']; mid = info['id']; tid = info['threadId']
        if cls == 'Urgent':
            keep_unread.add(mid)
            RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':info['reason'],'deadline':'','draftStatus':'none'})
        # Action attention already handled in draft pass. If no draft was created/existing, keep unread.
        elif cls == 'Action':
            if not any(a.get('messageId') == mid for a in RESULT['attention']):
                keep_unread.add(mid)
                RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':info['reason'],'deadline':'','draftStatus':'none'})
            else:
                keep_unread.add(mid)
        elif any(s in (h.get('subject','')+' '+info.get('snippet','')).lower() for s in ['medical record','test result','legal notice']):
            keep_unread.add(mid)
            RESULT['attention'].append({'messageId':mid,'threadId':tid,'from':h.get('from',''),'subject':h.get('subject',''),'reason':'Sensitive medical or legal content should be reviewed','deadline':'','draftStatus':'none'})
    read_ids = [i['id'] for i in processed_infos if i['id'] not in keep_unread and not i.get('read_done')]
    if read_ids:
        batch_modify(read_ids, remove=['UNREAD'])
        RESULT['markedRead'] += len(read_ids)
    RESULT['leftUnread'] = len(keep_unread) + sum(1 for i in processed_infos if i.get('force_left_unread'))
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'read_state','message':str(e)[:180]})

# 6. Archive stale read mail.
try:
    stale_ids = list_all_messages('is:read in:inbox older_than:1d')
    eligible = []
    for mid in stale_ids:
        try:
            m = get_msg(mid, 'full')
            labs = set(m.get('labelIds',[]) or [])
            if 'STARRED' in labs or cls_to_id.get('Urgent') in labs or cls_to_id.get('Action') in labs:
                continue
            eligible.append(mid)
        except Exception as e:
            RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'archive_fetch','messageId':mid,'message':str(e)[:160]})
    if eligible:
        batch_modify(eligible, remove=['INBOX'])
        RESULT['archived'] = len(eligible)
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'archive','message':str(e)[:180]})

# Final unread inbox IDs.
try:
    RESULT['unreadAfter'] = list_all_messages('is:unread in:inbox')
except Exception as e:
    RESULT['status'] = 'partial'; RESULT['errors'].append({'stage':'final_unread','message':str(e)[:180]})

# Deduplicate attention by messageId.
seen=set(); att=[]
for a in RESULT['attention']:
    if a['messageId'] in seen: continue
    seen.add(a['messageId']); att.append(a)
RESULT['attention'] = att
emit()
