"""Decode read-only alignment state captures and associate each browser run."""
from pathlib import Path
import json,struct,math,csv
p=Path(__file__).resolve().parent
f=lambda word:struct.unpack('<f',struct.pack('<I',int(word,16)))[0]
rows=[]
for line in(p/'swd-raw.log').read_text().splitlines():
 if not line.startswith('ALIGN,'):continue
 x=line.split(',');a=x[2:];flags=int(a[0],16);d=int(a[2],16);d=d-2**32 if d>=2**31 else d
 rows.append(dict(host_ms=int(x[1]),active=bool(flags&1),done=bool(flags&256),failed=bool(flags&65536),phase=int(a[1],16),direction=d,started_ms=int(a[3],16),phase_started_ms=int(a[4],16),mid_rad=f(a[5]),end_rad=f(a[6]),zero_electrical_rad=f(a[7]),angle_rad=f(a[8]),en_input=bool(int(a[9],16)&4096),en_output=bool(int(a[10],16)&4096)))
with(p/'swd-decoded.csv').open('w')as out:w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary=[]
for attempt in json.loads((p/'browser-results.json').read_text()):
 active=[r for r in rows if attempt['start_ms']<r['host_ms']<attempt['end_ms']and r['active']];started=active[0]['started_ms'];matching=[r for r in rows if r['started_ms']==started];done=next(r for r in matching if r['done']and not r['failed']);moved=abs(done['mid_rad']-done['end_rad']);phases={}
 for r in matching:
  if r['active']and r['phase']not in phases:phases[r['phase']]=r['phase_started_ms']
 duration=(phases[5]-started)&0xffffffff;duration+=700
 record={'attempt':attempt['attempt'],'browser_duration_ms':attempt['end_ms']-attempt['start_ms'],'mcu_minimum_duration_ms':duration,'mid_deg':math.degrees(done['mid_rad']),'end_deg':math.degrees(done['end_rad']),'travel_deg':math.degrees(moved),'electrical_deviation_rad':abs(moved*7-2*math.pi),'forward_endpoint_hold_ms':(phases[3]-phases[2])&0xffffffff,'return_endpoint_hold_ms':(phases[5]-phases[4])&0xffffffff,'direction':done['direction'],'ready':attempt['state']['state']=='READY','fault':attempt['state']['fault']};summary.append(record)
assert len(summary)==3 and all(r['ready']and r['fault']=='NONE'and r['electrical_deviation_rad']<=.8 and r['forward_endpoint_hold_ms']>=600 and r['return_endpoint_hold_ms']>=600 for r in summary)
(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
