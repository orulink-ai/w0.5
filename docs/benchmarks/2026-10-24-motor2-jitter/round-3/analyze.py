from pathlib import Path
import json,csv,struct,statistics,math
p=Path(__file__).resolve().parent
names=['shaft_angle_rad','controller_velocity_rad_s','velocity_setpoint_rad_s','uq_v','encoder_fast_velocity_rad_s','encoder_slow_velocity_rad_s','velocity_integral_v','velocity_pid_previous_v','electrical_zero_rad','sensor_direction','voltage_limit_v','velocity_p','velocity_i','encoder_unwrapped_angle_rad','encoder_sequence','pwm_high_us','pwm_period_us','pwm_captured_us','policy_zero_rad','policy_direction','gpiob_idr','gpiob_odr','tim3_arr','tim3_reserved_30','tim3_ccr1','tim3_ccr2']
integer={'encoder_sequence','pwm_high_us','pwm_period_us','pwm_captured_us','gpiob_idr','gpiob_odr','tim3_arr','tim3_reserved_30','tim3_ccr1','tim3_ccr2'}
serial=[json.loads(l)for l in(p/'serial.jsonl').read_text().splitlines()];states=[json.loads(l)for l in(p/'states.jsonl').read_text().splitlines()]
active=[s for s in states if s['state']['motors'][1]['closed_loop']['enabled']];start=active[0]['host_ms'];end=next(s['host_ms']for s in states if s['host_ms']>start and not s['state']['motors'][1]['closed_loop']['enabled']);step=next(s['host_ms']for s in active if s['state']['motors'][1]['closed_loop']['target_deg']==-56);back=next(s['host_ms']for s in active if s['host_ms']>step and s['state']['motors'][1]['closed_loop']['target_deg']==-64)
def phase(t):return 'baseline' if t<start else 'hold' if t<step else 'step_plus_8deg' if t<back else 'return' if t<end else 'stopped'
def stats(x):return dict(n=len(x),min=min(x),max=max(x),mean=statistics.mean(x),std=statistics.pstdev(x),peak_to_peak=max(x)-min(x))if x else {}
swd=[]
for l in(p/'swd-raw.log').read_text().splitlines():
 if not l.startswith('SWD_SAMPLE,'):continue
 x=l.split(',');t=int(x[1]);values=[]
 for name,word in zip(names,x[2:]):
  n=int(word,16)
  if name=='sensor_direction':v=(n&255)-256 if n&128 else n&255
  elif name=='policy_direction':v=n-2**32 if n>=2**31 else n
  elif name in integer:v=n
  else:v=struct.unpack('<f',struct.pack('<I',n))[0]
  values.append(v)
 r=dict(host_ms=t,time_s=(t-start)/1000,phase=phase(t),**dict(zip(names,values)))
 r['encoder_relative_deg']=(r['policy_direction']*r['encoder_unwrapped_angle_rad']-r['policy_zero_rad'])*180/math.pi
 r['pb12_input_high']=int(bool(r['gpiob_idr']&4096));r['pb12_output_high']=int(bool(r['gpiob_odr']&4096));swd.append(r)
trace=[]
for r in serial:
 x=r['text'].split(',');t=r['time_ms']
 if x[0]=='#FOC2_TRACE':trace.append(dict(host_ms=t,time_s=(t-start)/1000,phase=phase(t),mcu_ms=int(x[2]),id=int(x[3]),received_ms=int(x[4]),relative_deg=float(x[5]),target_deg=float(x[6]),planned_deg=float(x[7]),rpm=float(x[8]),uq_v=float(x[9]),limit_v=float(x[10])))
for name,rows in [('swd',swd),('trace',trace)]:
 with(p/(name+'.csv')).open('w')as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={'note':'Phase boundaries from 50Hz API state observations; UART receive and SWD clock times are approximate, non-atomic snapshots. Sampling is insufficient to exclude high-frequency vibration.','start':start,'step':step,'return':back,'stop':end,'swd_samples':len(swd),'trace_samples':len(trace),'swd_interval_ms':stats([b['host_ms']-a['host_ms']for a,b in zip(swd,swd[1:])]),'phases':{}}
for ph in ['baseline','hold','step_plus_8deg','return','stopped']:
 ss=[r for r in swd if r['phase']==ph];tt=[r for r in trace if r['phase']==ph]
 # Skip 100ms at each phase edge for GPIO/serial latency comparisons.
 mid=[r for r in ss if r['host_ms']>min((q['host_ms']for q in ss),default=0)+100 and r['host_ms']<max((q['host_ms']for q in ss),default=0)-100]
 summary['phases'][ph]={'trace':{k:stats([r[k]for r in tt])for k in['relative_deg','target_deg','rpm','uq_v']},'swd':{k:stats([r[k]for r in ss])for k in['encoder_relative_deg','controller_velocity_rad_s','velocity_setpoint_rad_s','uq_v','velocity_integral_v']},'pb12_input_high_fraction':statistics.mean([r['pb12_input_high']for r in mid])if mid else None,'pb12_output_high_fraction':statistics.mean([r['pb12_output_high']for r in mid])if mid else None,'ccr1':stats([r['tim3_ccr1']for r in mid]),'ccr2':stats([r['tim3_ccr2']for r in mid])}
summary['primary_unchanged']=all(not r['state']['motors'][0]['closed_loop']['enabled']and r['state']['motors'][0]['closed_loop']['last_id']==91933473 for r in states)
summary['faults']=sorted(set(r['state']['motors'][1]['closed_loop']['fault']for r in states));summary['active_feedback']=stats([r['encoder_relative_deg']for r in swd if start<=r['host_ms']<end]);summary['invalid_encoder_api_samples']=sum(not r['state']['motors'][1]['reading']['valid']for r in states)
(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(p/'events.json').write_text(json.dumps([{'host_ms':t,'event':k,'source':'API observation'}for k,t in [('enabled',start),('target_-56',step),('target_-64',back),('disabled',end)]],indent=2)+'\n')
print(json.dumps(summary,indent=2))
