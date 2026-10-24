"""Single-writer monitor, run on the Pi host, independent of page views."""
import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE = Path(os.environ.get('DASHBOARD_STATE','/var/lib/web-stack-status'))


def snapshot(name,value):
    STATE.mkdir(parents=True,exist_ok=True)
    temp=STATE/(name+'.tmp')
    temp.write_text(json.dumps({**value,'timestamp':time.time()}))
    temp.replace(STATE/(name+'.json'))


def health():
    import psutil
    vm=psutil.virtual_memory(); du=psutil.disk_usage('/'); io=psutil.net_io_counters()
    temp=None
    try:
        sensors=psutil.sensors_temperatures()
        for name in ('cpu_thermal','coretemp','k10temp','acpitz'):
            if sensors.get(name):
                temp=max(x.current for x in sensors[name]); break
    except (AttributeError,OSError): pass
    return {'uptime_seconds':time.time()-psutil.boot_time(),'cpu_pct':psutil.cpu_percent(interval=0.2),
            'cpu_count':psutil.cpu_count(),'cpu_temp_c':temp,'load_1m':os.getloadavg()[0],
            'mem':{'used_pct':vm.percent,'used_bytes':vm.total-vm.available,'total_bytes':vm.total},
            'disk':{'used_pct':du.percent,'used_bytes':du.used,'total_bytes':du.total},
            'net':{'tx_bytes':io.bytes_sent,'rx_bytes':io.bytes_recv},
            'health':'bad' if max(vm.percent,du.percent)>=95 or (temp or 0)>=85 else 'warn' if max(vm.percent,du.percent)>=80 or (temp or 0)>=70 else 'good'}


def init_db(db):
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS domains(hostname TEXT PRIMARY KEY,name TEXT,url TEXT,source TEXT,
      first_seen REAL,dns_changed_at TEXT,config_changed_at REAL,fingerprint TEXT,state TEXT,
      http_status INTEGER,latency_ms REAL,checked_at REAL,status_changed_at REAL,enabled INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS samples(hostname TEXT,timestamp REAL,state TEXT,http_status INTEGER,latency_ms REAL);
    CREATE INDEX IF NOT EXISTS samples_lookup ON samples(hostname,timestamp);
    CREATE TABLE IF NOT EXISTS events(hostname TEXT,timestamp REAL,kind TEXT,message TEXT);
    ''')
    db.commit()


def server_health():
    # Netdata stays on the existing private Tailscale network.
    url='http://100.117.231.66:19999/api/v1/allmetrics?format=json'
    with urllib.request.urlopen(url,timeout=5) as response: data=json.load(response)
    def dims(name): return {k:v.get('value',0) for k,v in data.get(name,{}).get('dimensions',{}).items()}
    cpu=dims('system.cpu'); ram=dims('system.ram'); net=dims('system.net')
    total=sum(ram.values())*1024**2
    used=ram.get('used',0)*1024**2
    disk_chart=next((value for value in data.values() if value.get('context')=='disk.space' and value.get('family')=='/'),None)
    disk=None
    if disk_chart:
        values={k:v.get('value',0) for k,v in disk_chart['dimensions'].items()}
        disk_total=sum(values.values())*1024**3
        disk_used=values.get('used',0)*1024**3
        disk={'total_bytes':disk_total,'used_bytes':disk_used,'used_pct':100*disk_used/disk_total if disk_total else 0}
    temps=[v['dimensions']['input']['value'] for k,v in data.items() if 'temperature_coretemp' in k and k.endswith('_input')]
    temp=max(temps) if temps else None
    if not cpu or not total: raise ValueError('Incomplete Netdata snapshot')
    latest=data.get('system.cpu',{}).get('last_updated',0)
    if time.time()-latest>90: raise ValueError('Stale Netdata snapshot')
    return {'uptime_seconds':dims('system.uptime').get('uptime'),'cpu_pct':100-cpu.get('idle',100),
      'cpu_temp_c':temp,'mem':{'used_pct':100*used/total,'used_bytes':used,'total_bytes':total},'disk':disk,
      'net':{'rx_rate':abs(net.get('InOctets',0))*1000/8,'tx_rate':abs(net.get('OutOctets',0))*1000/8},
      'health':'bad' if 100*used/total>=95 or (disk or {}).get('used_pct',0)>=95 or (temp or 0)>=85 else
      'warn' if 100*used/total>=80 or (disk or {}).get('used_pct',0)>=80 or (temp or 0)>=70 else 'good'}


def cloudflare(path):
    token=Path(os.environ.get('CLOUDFLARE_TOKEN_FILE','/etc/drcastiel/cloudflare-token')).read_text().strip()
    req=urllib.request.Request('https://api.cloudflare.com/client/v4/'+path,
        headers={'Authorization':'Bearer '+token,'User-Agent':'DrCastielMonitor'})
    with urllib.request.urlopen(req,timeout=12) as response: value=json.load(response)
    if not value.get('success'): raise ValueError('DNS sync failed')
    return value


def discovery():
    token=Path(os.environ.get('CLOUDFLARE_TOKEN_FILE','/etc/drcastiel/cloudflare-token'))
    records={}
    if token.exists():
        page=1
        while True:
            zones=cloudflare(f'zones?per_page=50&page={page}')
            for zone in zones['result']:
                rp=1
                while True:
                    result=cloudflare(f'zones/{zone["id"]}/dns_records?per_page=100&page={rp}')
                    for record in result['result']:
                        hostname=record['name'].lower()
                        if record['type'] not in ('A','AAAA','CNAME') or '*' in hostname or hostname.startswith('_'): continue
                        if hostname=='casa.drcastiel.com': continue
                        records[hostname]={'source':'Cloudflare DNS','dns_changed_at':record.get('modified_on'),
                          'fingerprint':hashlib.sha256(json.dumps({k:record.get(k) for k in ('type','content','proxied')},sort_keys=True).encode()).hexdigest()}
                    if rp>=result.get('result_info',{}).get('total_pages',1): break
                    rp+=1
            if page>=zones.get('result_info',{}).get('total_pages',1): break
            page+=1
        mode='Cloudflare DNS'; note='Domains sync automatically from Cloudflare every 5 minutes.'
    else:
        path=Path('/etc/cloudflared/config.yml')
        if path.exists():
            for hostname in re.findall(r'hostname:\s*[\"\x27]?([a-zA-Z0-9.-]+)',path.read_text()):
                hostname=hostname.lower()
                if hostname!='casa.drcastiel.com': records[hostname]={'source':'Cloudflare Tunnel','fingerprint':hostname}
        for path in Path('/etc/nginx/sites-enabled').glob('*'):
            try:
                for group in re.findall(r'server_name\s+([^;]+);',path.read_text()):
                    for hostname in group.split():
                        if re.fullmatch(r'[a-zA-Z0-9.-]+',hostname) and '.' in hostname and hostname!='casa.drcastiel.com':
                            records.setdefault(hostname,{'source':'Nginx','fingerprint':hostname})
            except OSError: pass
        mode='Tunnel + Nginx'
        note='New tunnel and Nginx sites sync automatically. Connect Cloudflare DNS to discover domains added only in DNS.'
    return records,{'mode':mode,'note':note,'dns_connected':token.exists()}


def upsert_domains(db,records):
    names={'drcastiel.com':'DrCastiel','www.drcastiel.com':'DrCastiel · www','dev.drcastiel.com':'Crown Dev Site',
      'admin.drcastiel.com':'Grafxolution Admin','customer.drcastiel.com':'Customer Portal','tracker.drcastiel.com':'Card Tracker','inbox.drcastiel.com':'Inbox'}
    now=time.time()
    for hostname,record in records.items():
        old=db.execute('SELECT fingerprint,enabled,source FROM domains WHERE hostname=?',(hostname,)).fetchone()
        fingerprint=record['fingerprint']
        if not old:
            db.execute('INSERT INTO domains(hostname,name,url,source,first_seen,dns_changed_at,config_changed_at,fingerprint,state) VALUES(?,?,?,?,?,?,?,?,?)',
              (hostname,names.get(hostname,hostname.split('.')[0].replace('-',' ').title()),'https://'+hostname,record['source'],now,record.get('dns_changed_at'),now,fingerprint,'unknown'))
            db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'discovered','Added to monitoring'))
        else:
            changed=old[0]!=fingerprint and old[2]==record['source']
            db.execute('UPDATE domains SET source=?,dns_changed_at=?,fingerprint=?,enabled=1,config_changed_at=CASE WHEN ? THEN ? ELSE config_changed_at END WHERE hostname=?',
              (record['source'],record.get('dns_changed_at'),fingerprint,changed,now,hostname))
            if changed: db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'configuration','Domain configuration changed'))
            if old[2]!=record['source']: db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'discovery','Connected '+record['source']+' discovery'))
            if not old[1]: db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'restored','Domain returned to discovery'))
    for (hostname,) in db.execute('SELECT hostname FROM domains WHERE enabled=1').fetchall():
        if hostname not in records:
            db.execute('UPDATE domains SET enabled=0 WHERE hostname=?',(hostname,))
            db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'removed','No longer present in domain discovery'))
    db.commit()


def public_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.port not in (None,443): return False
    addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
    return bool(addresses) and all(ipaddress.ip_address(x[4][0]).is_global for x in addresses)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not public_url(newurl): raise ValueError('Non-public redirect blocked')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def probe(item):
    hostname,url=item; start=time.monotonic(); status=None
    try:
        if not public_url(url): return hostname,'private',None,None
        opener=urllib.request.build_opener(SafeRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        req=urllib.request.Request(url,headers={'User-Agent':'DrCastielMonitor/2.0'})
        try:
            with opener.open(req,timeout=5) as response: status=response.status
        except urllib.error.HTTPError as error: status=error.code
        state='up' if 200<=status<400 else 'protected' if status in (401,403) else 'down'
    except Exception: state='down'
    return hostname,state,status,round((time.monotonic()-start)*1000)


def sample_domains(db):
    items=db.execute('SELECT hostname,url FROM domains WHERE enabled=1').fetchall()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(probe,items))
    now=time.time()
    for hostname,state,status,latency in results:
        previous=db.execute('SELECT state FROM domains WHERE hostname=?',(hostname,)).fetchone()[0]
        if previous!=state: db.execute('INSERT INTO events VALUES(?,?,?,?)',(hostname,now,'status',f'{previous.title()} → {state.title()}'))
        db.execute('UPDATE domains SET state=?,http_status=?,latency_ms=?,checked_at=?,status_changed_at=CASE WHEN ? THEN ? ELSE status_changed_at END WHERE hostname=?',
          (state,status,latency,now,previous!=state,now,hostname))
        db.execute('INSERT INTO samples VALUES(?,?,?,?,?)',(hostname,now,state,status,latency))
    db.execute('DELETE FROM samples WHERE timestamp<?',(now-30*86400,))
    db.execute('DELETE FROM events WHERE timestamp<?',(now-90*86400,))
    db.commit()


def main():
    STATE.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(STATE/'dashboard.sqlite3'); init_db(db)
    discover_at=sample_at=0
    while True:
        started=time.monotonic()
        try: snapshot('pi',health())
        except Exception as error: print('Pi collection failed:',type(error).__name__,flush=True)
        try: snapshot('server',server_health())
        except Exception as error: print('Server collection failed:',type(error).__name__,flush=True)
        now=time.time()
        if now>=discover_at:
            try:
                records,details=discovery()
                if records: upsert_domains(db,records)
                snapshot('discovery',details)
            except Exception as error: print('Discovery failed:',type(error).__name__,flush=True)
            discover_at=now+300
        if now>=sample_at:
            try: sample_domains(db)
            except Exception as error: print('Domain check failed:',type(error).__name__,flush=True)
            sample_at=now+60
        time.sleep(max(1,15-(time.monotonic()-started)))


if __name__=='__main__': main()
