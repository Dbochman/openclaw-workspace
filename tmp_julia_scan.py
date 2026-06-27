import subprocess,json,os,sys,base64,re,email.utils
ACCOUNT='julia.joy.jennings@gmail.com'
os.environ['GOOGLE_WORKSPACE_CLI_ACCOUNT']=ACCOUNT

def gws(args, params=None, body=None):
    cmd=['gws']+args
    if params is not None:
        cmd += ['--params', json.dumps(params,separators=(',',':'))]
    if body is not None:
        cmd += ['--json', json.dumps(body,separators=(',',':'))]
    cmd += ['--account', ACCOUNT]
    p=subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode!=0:
        raise Exception(p.stderr or p.stdout)
    return json.loads(p.stdout) if p.stdout.strip() else {}

def list_all(q):
    ids=[]; tok=None
    while True:
        params={'userId':'me','q':q,'maxResults':100}
        if tok: params['pageToken']=tok
        d=gws(['gmail','users','messages','list'], params)
        ids += [m['id'] for m in d.get('messages',[])]
        tok=d.get('nextPageToken')
        if not tok: break
    return ids

def headers(msg):
    return {h['name'].lower():h.get('value','') for h in msg.get('payload',{}).get('headers',[])}
ids=list_all('is:unread in:inbox')
print('COUNT',len(ids))
for i,mid in enumerate(ids,1):
    msg=gws(['gmail','users','messages','get'], {'userId':'me','id':mid,'format':'full'})
    h=headers(msg)
    print(json.dumps({'i':i,'id':mid,'thread':msg.get('threadId'),'from':h.get('from',''),'subject':h.get('subject',''),'date':h.get('date',''),'labels':msg.get('labelIds',[]),'snippet':msg.get('snippet','')[:220]}, ensure_ascii=False))
