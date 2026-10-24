"use strict";
const assert=require('node:assert/strict');
const {motorState,AdditionalMotorPanel}=require('../encoder_dashboard/static/components/motor-workbench.js');
const first={supported:true,available:true,state:'RUNNING',run_id:10};
const second={supported:true,available:true,state:'READY',run_id:0};
const full={connected:true,signal:'valid',reading:{angle_deg:30},closed_loop:first,encoder_mode:'dual_control',
  motors:[{id:1,signal:'valid',reading:{angle_deg:30},closed_loop:first},
          {id:2,signal:'invalid',reading:{angle_deg:220},closed_loop:second}]};
assert.equal(motorState(full,1),full);
assert.equal(motorState(full,2).closed_loop,second);
assert.equal(motorState(full,2).signal,'invalid');
assert.equal(full.closed_loop,first,'Projection never changes the primary motor state');
assert.equal(motorState({...full,motors:[]},2).closed_loop.supported,false);
assert.throws(()=>motorState(full,3));
let options,displayed;
class FakePanel{constructor(_,value){options=value;}render(value){displayed=value;}}
const calls=[],updates=[];
const workbench=new AdditionalMotorPanel({}, {Panel:FakePanel,onState:value=>updates.push(value),
  post:async(path,payload)=>{calls.push([path,payload]);return path.endsWith('heartbeat')?{ok:true,run_id:12}:full;}});
workbench.render(full);assert.equal(displayed.closed_loop,second);
(async()=>{
  const selected=await options.send({action:'stop'});
  assert.equal(selected.closed_loop,second);assert.equal(updates[0],full);
  await options.heartbeat(12);
  assert.deepEqual(calls,[['/api/foc/2',{action:'stop'}],['/api/foc/2/heartbeat',{run_id:12}]]);
  assert.equal(full.closed_loop,first);
  console.log('Independent motor workbench routing passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
