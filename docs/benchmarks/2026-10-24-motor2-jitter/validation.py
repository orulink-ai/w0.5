"""Compare fixed-target stability after a one-second settling allowance."""
import bisect,csv,json,math,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def measure(folder):
 p=ROOT/folder;events=json.loads((p/'browser-events.json').read_text());release=next(e['host_ms']for e in events if e['event']=='release');stop=next(e['host_ms']for e in events if e['event']=='stop_click');plan=json.loads((p/'plan.json').read_text());target=plan['targets'][-1]
 if(p/'angle-frames.csv').exists():
  raw=[(float(r['host_ms']),float(r['relative_deg']))for r in csv.DictReader((p/'angle-frames.csv').open())];source='SWD PWM tracker'
 else:
  raw=[]
  for line in(p/'serial.jsonl').read_text().splitlines():
   r=json.loads(line);x=r['text'].split(',')
   if x[0]=='#FOC2_TRACE':raw.append((r['time_ms'],float(x[5])))
  source='UART TRACE'
 values=[a for t,a in raw if release+1000<t<stop-100];mean=statistics.mean(values);pp=max(values)-min(values);std=statistics.pstdev(values)
 states=[json.loads(l)['state']for l in(p/'states.jsonl').read_text().splitlines()];faults=sorted(set(s['motors'][1]['closed_loop']['fault']for s in states));primary_unchanged=all(not s['motors'][0]['closed_loop']['enabled']and s['motors'][0]['closed_loop']['last_id']==plan['primary_id']for s in states)
 result=dict(folder=folder,source=source,settled_samples=len(values),target_deg=target,mean_deg=mean,mean_error_deg=mean-target,std_deg=std,peak_to_peak_deg=pp,minimum_deg=min(values),maximum_deg=max(values),faults=faults,primary_unchanged=primary_unchanged)
 # This is a bench acceptance envelope for the current unloaded assembly.
 result['accepted']=len(values)>=15 and pp<=.5 and std<=.12 and abs(mean-target)<=.3 and faults==['NONE'] and primary_unchanged
 late=[a for t,a in raw if release+2000<t<stop-100]
 if len(late)>=15:
  late_mean=statistics.mean(late);late_pp=max(late)-min(late);late_std=statistics.pstdev(late)
  result['after_two_seconds']=dict(n=len(late),mean_deg=late_mean,mean_error_deg=late_mean-target,peak_to_peak_deg=late_pp,std_deg=late_std,accepted=late_pp<=.5 and late_std<=.12 and abs(late_mean-target)<=.3 and faults==['NONE'] and primary_unchanged)
 inputs=[(e['host_ms'],e['value'])for e in json.loads((p/'browser-inputs.json').read_text())if e['type']=='input'];ts=[r[0]for r in inputs]
 if inputs:
  errors=[]
  for t,a in raw:
   if ts[0]<=t<release:
    idx=bisect.bisect_right(ts,t)-1
    if idx>=0:errors.append(a-inputs[idx][1])
  if errors:result['drag_error_deg']=dict(rms=math.sqrt(statistics.mean(e*e for e in errors)),max_absolute=max(abs(e)for e in errors),n=len(errors))
  last_target_ms=inputs[-1][0];bad=[t for t,a in raw if last_target_ms<t<stop-100 and abs(a-target)>.5];result['last_outside_half_degree_ms_after_final_input']=max(0,max(bad,default=last_target_ms)-last_target_ms)
 (p/'validation.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
 folders=['round-4-drag','round-5-ramp100','round-6-ramp100-repeat','round-7-serial-only','round-8-firmware','round-9-p010','round-10-final','round-11-final-serial']
 results=[]
 for folder in folders:
  try:results.append(measure(folder))
  except FileNotFoundError:continue
 (ROOT/'validation-summary.json').write_text(json.dumps(results,indent=2)+'\n')
 for r in results:print(f"{r['folder']}: pp={r['peak_to_peak_deg']:.3f} std={r['std_deg']:.3f} err={r['mean_error_deg']:.3f} accepted={r['accepted']}")
