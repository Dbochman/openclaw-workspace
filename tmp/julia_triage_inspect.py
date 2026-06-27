#!/usr/bin/env python3
import subprocess, json, sys, base64, re, html, email.utils
ACCOUNT='julia.joy.jennings@gmail.com'

def gws(resource, method, params=None, body=None):
    cmd=['gws','gmail']+resource.split()+[method]
    if params is not None:
        cmd += ['--params', json.dumps(params,separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body,separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode!=0:
        raise RuntimeError(f"cmd failed {cmd}\nSTDOUT:{p.stdout}\nSTDERR:{p.stderr}")
    return json.loads(p.stdout) if p.stdout.strip() else {}

def list_ids(q):
    ids=[]; token=None
    while True:
        params={'userId':'me','q':q,'maxResults':100}
        if token: params['pageToken']=token
        d=gws('users messages','list',params)
        ids.extend([m['id'] for m in d.get('messages',[])])
        token=d.get('nextPageToken')
        if not token: return ids

def headers(msg):
    return {h['name'].lower():h.get('value','') for h in msg.get('payload',{}).get('headers',[])}

def get(id): return gws('users messages','get',{'userId':'me','id':id,'format':'full'})

for name,q in [('spam','in:inbox category:promotions is:unread older_than:3d'),('unread','is:unread in:inbox')]:
    ids=list_ids(q)
    print('\n==',name,len(ids),'==')
    for i,id in enumerate(ids[:250]):
        m=get(id); h=headers(m)
        print(f"{i+1:3} {id} labels={','.join(m.get('labelIds',[]))}\n    From: {h.get('from','')}\n    Subj: {h.get('subject','')}\n    Date: {h.get('date','')}\n    Snip: {m.get('snippet','')[:220].replace(chr(10),' ')}")
