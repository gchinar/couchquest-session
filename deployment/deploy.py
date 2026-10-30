"""Deploy CouchQuest to the named Minikube context; never uses the default context."""
import argparse, json, secrets, subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--context',default='couchquest')
p.add_argument('--manifest',default=str(Path(__file__).with_name('kubernetes.yaml')))
p.add_argument('--service',choices=['catalog','session','all'],default='all')
a=p.parse_args()
if a.context != 'couchquest':
    p.error('This demonstration script deploys only to the couchquest context.')
base=['minikube','-p',a.context,'kubectl','--','--context',a.context]
def run(args, data=None):
    return subprocess.run(base+args,input=None if data is None else json.dumps(data),text=True,check=True)
run(['apply','-f','-'],{'apiVersion':'v1','kind':'Namespace','metadata':{'name':'couchquest'}})
services=['catalog','session'] if a.service=='all' else [a.service]
for name in services:
    exists=subprocess.run(base+['-n','couchquest','get','secret',name+'-secret','-o','name'],capture_output=True,text=True)
    if exists.returncode:
        password=secrets.token_hex(24)
        db='catalog' if name=='catalog' else 'sessions'
        run(['apply','-f','-'],{'apiVersion':'v1','kind':'Secret','metadata':{'name':name+'-secret','namespace':'couchquest'},'type':'Opaque','stringData':{'password':password,'database-url':f'postgresql+psycopg://{db}:{password}@{name}-db:5432/{db}'}})
run(['apply','-f',a.manifest])
for name in services:
    run(['-n','couchquest','rollout','status','deployment/'+name+'-db','--timeout=300s'])
    run(['-n','couchquest','rollout','status','deployment/'+name,'--timeout=300s'])
run(['-n','couchquest','get','deployments,pods,services,pvc'])
