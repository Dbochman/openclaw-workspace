#!/usr/bin/env python3
import subprocess,json,base64,re,html
ACCOUNT='julia.joy.jennings@gmail.com'
ids=['19ef7662cea1b276','19ef765fe44de0ee','19ef536433778b03','19ea87a05e60456d']
def gws(res,meth,params=None,body=None):
 cmd=['gws','gmail']+res.split()+[meth]
 if params: cmd+=['--params',json.dumps(params,separators=(',',':'))]
 if body: cmd+=['--json',json.dumps(body,separators=(',',':'))]
 cmd+=['--account',ACCOUNT]
 p=subprocess.run(cmd,text=True,capture_output=True,timeout=90)
 if p.returncode: raise Exception(p.stderr+p.stdout)
 return json.loads(p.stdout)
def decode(s):
 if not s: return ''
 return base64.urlsafe_b64decode(s+'='*((4-len(s)%4)%4)).decode('utf-8','replace')
def walk(part):
 out=[]
 mt=part.get('mimeType','')
 data=part.get('body',{}).get('data')
 if data and (mt.startswith('text/') or mt in ('text/plain','text/html')):
  txt=decode(data)
  if mt=='text/html':
   txt=re.sub(r'<(br|/p|/div|/tr|/li)[^>]*>','\n',txt,flags=re.I); txt=re.sub(r'<[^>]+>',' ',txt); txt=html.unescape(txt)
  out.append(txt)
 for p in part.get('parts',[]) or []: out+=walk(p)
 return out
for id in ids:
 m=gws('users messages','get',{'userId':'me','id':id,'format':'full'})
 h={x['name'].lower():x.get('value','') for x in m.get('payload',{}).get('headers',[])}
 print('\n----',id,m.get('threadId'),m.get('labelIds'))
 print(h.get('from'), '|', h.get('subject'), '|', h.get('date'))
 txt='\n'.join(walk(m.get('payload',{})))
 txt=re.sub(r'\n{3,}','\n\n',txt); txt=re.sub(r'[ \t]{2,}',' ',txt)
 print(txt[:4000])
