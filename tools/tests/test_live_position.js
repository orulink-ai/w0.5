"use strict";
const assert = require("node:assert/strict");
const {LivePositionQueue,canSendTarget}=require("../encoder_dashboard/static/components/live-position.js");
class Clock {
  constructor(){this.time=0;this.next=1;this.tasks=new Map();}
  now(){return this.time;}
  setTimeout(fn,delay){const id=this.next++;this.tasks.set(id,{at:this.time+delay,fn});return id;}
  clearTimeout(id){this.tasks.delete(id);}
  advance(ms){this.time+=ms;for(const[id,task]of [...this.tasks])if(task.at<=this.time){this.tasks.delete(id);task.fn();}}
}
const state=(patch={},outer={})=>({connected:true,signal:"valid",closed_loop:{available:true,
  protocol_version:4,state:"RUNNING",mode:"POSITION",enabled:true,calibrated:true,sensor_valid:true,
  run_id:20,owned_run_id:20,last_id:20,soft_min_deg:-90,soft_max_deg:90,
  command:{status:"accepted",action:"target",id:21},...patch},...outer});
const flush=async()=>{await Promise.resolve();await Promise.resolve();};
function fixture(){
 const clock=new Clock(),requests=[],responses=[],errors=[];
 const queue=new LivePositionQueue({clock,send:payload=>new Promise((resolve,reject)=>requests.push({payload,resolve,reject,at:clock.now()})),
  onState:value=>responses.push(value),onError:error=>errors.push(error)});
 return {clock,requests,responses,errors,queue};
}
(async()=>{
  assert.equal(canSendTarget(state(),20,"position"),true);
  for(const patch of [{protocol_version:3},{available:false},{state:"READY",enabled:false},{mode:"VELOCITY"},
    {enabled:false},{sensor_valid:false},{calibrated:false},{run_id:21},{owned_run_id:21},{owned_run_id:null}])
    assert.equal(canSendTarget(state(patch),20,"position"),false);
  assert.equal(canSendTarget(state(),null,"position"),false);
  assert.equal(canSendTarget(state(),20,"velocity"),false);
  assert.equal(canSendTarget(state({}, {connected:false}),20,"position"),false);
  assert.equal(canSendTarget(state({}, {signal:"stale"}),20,"position"),false);
  let {clock,requests,responses,errors,queue}=fixture();
  assert.equal(queue.intervalMs,50,"Default target update interval is 50 ms (20 Hz)");
  queue.observe(state({state:"READY",enabled:false,run_id:0,owned_run_id:null}),null,"position");
  assert.equal(queue.input(30),false);assert.equal(requests.length,0,"READY only edits local target");
  queue.observe(state(),20,"position");assert.equal(requests.length,0,"Render/ownership never sends");
  assert.equal(queue.input(NaN),false);assert.equal(queue.input(91),false);assert.equal(queue.input(-91),false);
  queue.input(10);queue.input(20);queue.input(30);queue.release(40);
  assert.equal(requests.length,1,"Only one TARGET in flight");
  assert.deepEqual(requests[0].payload,{action:"target",run_id:20,target_deg:10});
  clock.advance(25);requests[0].resolve(state());await flush();
  assert.equal(requests.length,1);clock.advance(24);assert.equal(requests.length,1);
  clock.advance(1);assert.equal(requests.length,2);assert.equal(requests[1].payload.target_deg,40,"Release's latest value survives coalescing");
  queue.input(50);queue.release(60);clock.advance(25);requests[1].resolve(state());await flush();
  clock.advance(25);assert.equal(requests.length,3);assert.equal(requests[2].payload.target_deg,60);
  assert.deepEqual(requests.map(request=>request.at),[0,50,100],"At most twenty target writes per second");
  assert.equal(requests.every(request=>request.payload.run_id===20),true,"TARGET does not create another run");
  queue.clear();requests[2].resolve(state());await flush();assert.equal(responses.length,2,"Late canceled response never updates UI");
  assert.equal(clock.tasks.size,0);
  ({clock,requests,responses,errors,queue}=fixture());queue.observe(state(),20,"position");
  queue.input(10);queue.input(20);queue.release(30);clock.advance(250);
  assert.equal(requests.length,1,"A slow ACK keeps only one request in flight, even below 20 Hz");
  requests[0].resolve(state());await flush();
  assert.equal(requests.length,2);assert.equal(requests[1].at,250);
  assert.equal(requests[1].payload.target_deg,30,"Final released target is sent after a slow ACK");
  queue.clear();requests[1].resolve(state());await flush();
  ({clock,requests,responses,errors,queue}=fixture());queue.observe(state(),20,"position");
  queue.input(10);queue.release(45);requests[0].resolve(state());await flush();
  queue.observe(state({available:false}),20,"position");clock.advance(500);
  assert.equal(requests.length,1,"Stale device state cancels the throttled final target");
  ({clock,requests,responses,errors,queue}=fixture());queue.observe(state(),20,"position");queue.input(10);queue.release(80);
  queue.clear();queue.observe(state(),null,"position");requests[0].resolve(state());await flush();clock.advance(1000);
  assert.equal(requests.length,1,"STOP/pagehide drops pending release");assert.equal(responses.length,0);
  queue.observe(state(),20,"velocity");assert.equal(queue.input(30),false,"Velocity never sends TARGET");
  queue.observe(state({protocol_version:3}),20,"position");assert.equal(queue.release(30),false,"Old firmware never receives TARGET");
  queue.observe(state({}, {connected:false}),20,"position");queue.observe(state(),null,"position");
  assert.equal(queue.input(30),false,"Reconnect does not own or restart");
  ({clock,requests,responses,errors,queue}=fixture());queue.observe(state(),20,"position");queue.input(10);queue.input(60);
  queue.observe(state({run_id:21,owned_run_id:21,last_id:21}),20,"position");
  requests[0].resolve(state());await flush();clock.advance(500);
  assert.equal(requests.length,1,"Changed run clears pending queue");assert.equal(responses.length,0);
  ({clock,requests,responses,errors,queue}=fixture());queue.observe(state(),20,"position");queue.input(10);queue.input(20);
  requests[0].reject(new Error("NACK"));await flush();clock.advance(500);
  assert.deepEqual(errors,["NACK"]);assert.equal(requests.length,1);assert.equal(queue.context,null,"Failure revokes queue eligibility");
  ({queue,requests,errors}=fixture());queue.observe(state(),20,"position");queue.input(10);
  requests[0].resolve(state({command:{status:"accepted",action:"position",id:25}}));await flush();
  assert.equal(errors.length,1,"A non-TARGET acknowledgement is not success");
  console.log("Live position queue tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
