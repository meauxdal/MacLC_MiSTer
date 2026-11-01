#!/usr/bin/env python3
import sys,hashlib,json,subprocess
from pathlib import Path
sys.path.insert(0,'fixtures/research/software-bringup')
from inspect_resources import resources
root=Path('local/experiments/startup-runtime')
rb=str(Path('local/experiments/system-baseline/rb/rb-cli.exe').resolve())
image='local/hardfiles/Apple-II_100MB.hda'
result={'image':{'bytes':Path(image).stat().st_size,'sha256':hashlib.sha256(Path(image).read_bytes()).hexdigest()},'files':[]}
for i,path in enumerate(['/IIe Startup','/System 7.1.2/System','/System 7.1.2/Finder','/System 7.1.2/Extensions/ProDOS File System']):
 archive=root/f'selected-{i}.hqx'; out=root/f'selected-{i}'
 subprocess.run([rb,'get-binhex',image,path,str(archive)],check=True,capture_output=True)
 subprocess.run([rb,'archive','extract',str(archive),str(out),'--format','raw'],check=True,capture_output=True)
 p=next(p for p in out.iterdir() if not p.name.endswith('.rsrc'))
 b=p.with_name(p.name+'.rsrc').read_bytes()
 rs=list(resources(b))
 rec={'path':path,'data_bytes':len(p.read_bytes()),'data_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'resource_bytes':len(b),'resource_sha256':hashlib.sha256(b).hexdigest(),'versions':[{'id':m['id'],'hex':d.hex(),'short':d[7:7+d[6]].decode('mac_roman')} for m,d in rs if m['type']=='vers']}
 result['files'].append(rec)
 if i==0:
  old=dict(((m['type'],m['id']),d) for m,d in resources(Path('local/experiments/startup-protocol/app221/IIe Startup.rsrc').read_bytes()))
  result['startup_changed_resources']=[{'type':m['type'],'id':m['id'],'installed_bytes':len(d),'old_bytes':len(old.get((m['type'],m['id']),b''))} for m,d in rs if old.get((m['type'],m['id']))!=d]
  for m,d in rs:
   if m['type']=='CODE' and m['id']==2:(root/'CODE2.bin').write_bytes(d)
Path('fixtures/experiments/startup-runtime/inventory.json').write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=True))
