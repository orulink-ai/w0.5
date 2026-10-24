import json,csv,math,struct,statistics
from pathlib import Path
p=Path(__file__).resolve().parent;events=json.loads((p/'events.json').read_text());browser=json.loads((p/'browser-events.json').read_text());plan=json.loads((p/'plan.json').read_text());start=next(e['host_ms']for e in events if e['event']=='enabled');stop=next(e['host_ms']for e in events if e['event']=='disabled');release=next(e['host_ms']for e in browser if e['event']=='release');lasttarget=max(e['host_ms']for e in events if e['event']=='target');states=[json.loads(l)for l in(p/'states.jsonl').read_text().splitlines()];serial=[json.loads(l)for l in(p/'serial.jsonl').read_text().splitlines()]
def f(x):return struct.unpack('<f',struct.pack('<I',int(x,16)))[0]
def phase(t):return 'baseline'if t<start else 'drag'if t<release else 'released_hold'if t<stop else 'stopped'
def stats(v):return {'n':len(v),'min':min(v),'max':max(v),'mean':statistics.mean(v),'std':statistics.pstdev(v),'peak_to_peak':max(v)-min(v)}if v else {}
angles=[];control=[]
for l in(p/'swd-raw.log').read_text().splitlines():
 x=l.split(',')
 if x[0]=='ANGLE':
  t=int(x[1]);a=x[2:];angles.append(dict(host_ms=t,time_s=(t-start)/1000,phase=phase(t),sequence=int(a[0],16),captured_us=int(a[11],16),raw_angle_deg=f(a[4])*180/math.pi,relative_deg=plan['direction']*(f(a[3])*180/math.pi-plan['zero_raw_deg']),slow_rad_s=plan['direction']*f(a[5]),fast_rad_s=plan['direction']*f(a[7]),high_us=int(a[9],16),period_us=int(a[10],16)))
 elif x[0]=='CONTROL':
  t=int(x[1]);a=x[2:];control.append(dict(host_ms=t,time_s=(t-start)/1000,phase=phase(t),velocity_rad_s=f(a[0]),angle_sp_rad=f(a[1]),velocity_sp_rad_s=f(a[2]),current_sp=f(a[3]),ud_v=f(a[4]),uq_v=f(a[5]),integral_v=f(a[6]),enable_input=bool(int(a[7],16)&4096),enable_output=bool(int(a[8],16)&4096),ccr1=int(a[9],16),ccr2=int(a[10],16),ccr3=int(a[11],16)))
# New PWM sequence samples only; SWD is not an atomic frame read.
unique=[];seen=set()
for r in angles:
 if r['sequence']not in seen:unique.append(r);seen.add(r['sequence'])
for name,rows in [('angle-samples',angles),('angle-frames',unique),('control',control)]:
 with(p/(name+'.csv')).open('w')as out:
  w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={'swd_polls':len(angles),'unique_pwm_sequences':len(unique),'control_samples':len(control),'poll_interval_ms':stats([b['host_ms']-a['host_ms']for a,b in zip(angles,angles[1:])]),'phase_stats':{},'state_faults':sorted(set(r['state']['motors'][1]['closed_loop']['fault']for r in states)),'overspeed_toggle_states':sorted(set(r['state']['motors'][1]['closed_loop']['overspeed_enabled']for r in states)),'primary_unchanged':all(not r['state']['motors'][0]['closed_loop']['enabled']and r['state']['motors'][0]['closed_loop']['last_id']==plan['primary_id']for r in states),'raw_nack':[r for r in serial if r['text'].startswith('#FOC2_NACK')],'phases_ms':{'start':start,'release':release,'last_target':lasttarget,'stop':stop}}
for ph in ['baseline','drag','released_hold','stopped']:
 a=[r for r in unique if r['phase']==ph];c=[r for r in control if r['phase']==ph and start+100<r['host_ms']<stop-100];s=[r['state']['motors'][1]['closed_loop']for r in states if phase(r['host_ms'])==ph]
 summary['phase_stats'][ph]={'angle_deg':stats([r['relative_deg']for r in a]),'fast_rad_s':stats([r['fast_rad_s']for r in a]),'slow_rad_s':stats([r['slow_rad_s']for r in a]),'uq_v':stats([r['uq_v']for r in c]),'integral_v':stats([r['integral_v']for r in c]),'controller_velocity_rad_s':stats([r['velocity_rad_s']for r in c]),'velocity_sp_rad_s':stats([r['velocity_sp_rad_s']for r in c]),'ccr1':stats([r['ccr1']for r in c]),'ccr2':stats([r['ccr2']for r in c]),'ccr3':stats([r['ccr3']for r in c]),'enable_low_control_samples':sum(not r['enable_input']or not r['enable_output']for r in c),'api_speed_rpm':stats([r['velocity_rpm']for r in s]),'api_targets':sorted(set(r['target_deg']for r in s)),'api_states':sorted(set(r['state']for r in s))}
# Frequency scan of fixed-target hold, using PWM capture timestamps (no uniform resampling).
hold=[r for r in unique if release+100<r['host_ms']<stop-50];t0=hold[0]['captured_us'];ts=[((r['captured_us']-t0)&0xffffffff)/1e6 for r in hold];mean=statistics.mean(r['relative_deg']for r in hold);ys=[r['relative_deg']-mean for r in hold];power=[]
for i in range(20,2001):
 hz=i/20;w=2*math.pi*hz;re=sum(y*math.cos(w*t)for t,y in zip(ts,ys));im=sum(y*math.sin(w*t)for t,y in zip(ts,ys));power.append((re*re+im*im,hz))
summary['hold_frequency_estimate_hz']=max(power)[1];summary['hold_frame_interval_us']=stats([((b['captured_us']-a['captured_us'])&0xffffffff)for a,b in zip(hold,hold[1:])]);summary['hold_voltage_sign_reversals']=sum(a['uq_v']*b['uq_v']<0 for a,b in zip([r for r in control if r['phase']=='released_hold'],[r for r in control if r['phase']=='released_hold'][1:]));(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
