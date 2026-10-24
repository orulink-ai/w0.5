import assert from 'node:assert/strict';
import {createMotionClock} from '../encoder_dashboard/static/robot-motion-clock.mjs';
let now=0,id=0;const pending=new Map(),frames=[];
const clock=createMotionClock({onFrame:t=>frames.push(t),requestFrame:fn=>{pending.set(++id,fn);return id;},cancelFrame:id=>pending.delete(id),now:()=>now});
const tick=(delta)=>{now+=delta;const jobs=[...pending.values()];pending.clear();jobs.forEach(fn=>fn(now));};
clock.setActive(true);clock.play();clock.play();assert.equal(pending.size,1,'play cannot create duplicate frame loops');
tick(100);assert.ok(clock.time>0);
clock.pause();const paused=clock.time;assert.equal(pending.size,0);tick(1000);assert.equal(clock.time,paused);
clock.play();tick(100);assert.ok(clock.time>paused);
clock.setActive(false);const hidden=clock.time;tick(10000);assert.equal(clock.time,hidden,'hidden/loading time must not advance choreography');
clock.setActive(true);tick(100);assert.ok(clock.time-hidden<0.2,'resume does not jump forward by hidden time');
clock.reset();assert.equal(clock.time,0);assert.equal(frames.at(-1),0);assert.equal(pending.size,0);
clock.seek(9.5);assert.equal(clock.time,9.5);assert.equal(frames.at(-1),9.5);assert.equal(pending.size,0);
clock.seek(-1);assert.equal(clock.time,0);
clock.play();clock.dispose();assert.equal(pending.size,0);clock.play();assert.equal(pending.size,0,'disposed player must not schedule frames');
console.log('Robot animation clock tests passed');

for (const hz of [60,90,120,144]) {
  let stamp=0,count=0,next;
  const c=createMotionClock({onFrame:()=>count++,requestFrame:fn=>{next=fn;return 1;},cancelFrame:()=>{next=null;},now:()=>stamp});
  c.setActive(true);c.play();
  for (let frame=1;frame<=hz*5;frame++) {stamp=frame*1000/hz;const job=next;next=null;job(stamp);}
  assert.equal(count,120,`${hz}Hz display must produce24fps, not drop accumulated frame time`);
  assert.ok(Math.abs(c.time-5)<1e-9,'visible playback must retain elapsed wall-clock time');
  c.dispose();
}
console.log('60/90/120/144Hz cadence and seek tests passed');
