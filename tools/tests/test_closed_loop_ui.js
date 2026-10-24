"use strict";
const assert = require("node:assert/strict");
const {viewModel} = require("../encoder_dashboard/static/components/closed-loop.js");
const state = (patch = {}, outer = {}) => ({connected:true, signal:"valid", closed_loop:{supported:true,
  available:true, protocol_version:3, state:"READY", calibrated:true, enabled:false, sensor_valid:true, command:{status:"idle"}, ...patch}, ...outer});
assert.equal(viewModel(state()).ready, true);
assert.equal(viewModel(state({state:"UNCALIBRATED"})).calibrate, true);
assert.equal(viewModel(state({state:"UNCALIBRATED"})).ready, false);
for (const phase of ["CALIBRATING", "RUNNING", "FAULT"]) {
  assert.equal(viewModel(state({state:phase})).ready, false);
  assert.equal(viewModel(state({state:phase})).calibrate, false);
}
assert.equal(viewModel(state({available:false})).ready, false);
assert.equal(viewModel(state({}, {signal:"stale"})).ready, false);
assert.equal(viewModel(state({}, {signal:"invalid"})).calibrate, false);
assert.equal(viewModel(state({}, {connected:false})).stop, false);
assert.equal(viewModel(state({available:false}), true).stop, true);
assert.equal(viewModel(state(), true).ready, false);
assert.equal(viewModel(state({command:{status:"pending"}})).ready, false);
assert.equal(viewModel(state({state:"UNCALIBRATED", command:{status:"accepted"}})).ready, false);
assert.equal(viewModel(state({supported:false})).visible, false);
assert.notEqual(viewModel(state({state:"RUNNING", calibrated:false, enabled:true})).label, "闭环运行中");
assert.notEqual(viewModel(state({state:"RUNNING", sensor_valid:false, enabled:true})).label, "闭环运行中");
assert.notEqual(viewModel(state({state:"RUNNING", enabled:false})).label, "闭环运行中");
assert.notEqual(viewModel(state({calibrated:false})).label, "已校准 · 已停止");
assert.equal(viewModel(state({settling:true})).ready, false);
assert.equal(viewModel(state()).hasRelative, true);
assert.equal(viewModel(state({calibrated:false})).hasRelative, false);
assert.equal(viewModel(state({sensor_valid:false})).hasRelative, false);
assert.equal(viewModel(state()).enableLabel, "已关闭");
assert.equal(viewModel(state({enabled:true})).enableLabel, "已开启");
assert.equal(viewModel(state({enabled:false,available:false})).enableLabel, "未知");
assert.equal(viewModel(state({enabled:false}, {connected:false})).enableLabel, "未知");
assert.equal(viewModel(state({enabled:null})).enableLabel, "未知");
console.log("Closed-loop UI state tests passed");
assert.equal(viewModel(state({protocol_version:1})).ready,false);
assert.equal(viewModel(state({protocol_version:1,state:"UNCALIBRATED"})).calibrate,false);
assert.equal(viewModel(state({protocol_version:1})).stop,true);
assert.equal(viewModel(state({protocol_version:2})).ready,false);
assert.equal(viewModel(state({protocol_version:2,state:"UNCALIBRATED"})).calibrate,false);

// Exercise the actual panel request lifecycle without a browser or hardware.
const {LeaseKeeper}=require("../encoder_dashboard/static/components/lease-keeper.js");
const {ClosedLoopPanel}=require("../encoder_dashboard/static/components/closed-loop.js");
const accepted=(action="position",id=20)=>({connected:true,closed_loop:{available:true,protocol_version:3,
  state:"RUNNING",run_id:id,last_id:id,owned_run_id:id,command:{id,action,status:"accepted"}}});
function testPanel() {
  const panel=Object.create(ClosedLoopPanel.prototype);
  const requests=[],pulses=[];
  panel.state={connected:true};panel.busy=false;panel.requestSequence=0;panel.error="";
  panel.lease=new LeaseKeeper({clock:{setTimeout:()=>1,clearTimeout:()=>{}},heartbeat:async run=>{
    pulses.push(run);return {ok:true,run_id:run};}});
  panel.payload=action=>({action});panel.render=()=>{};
  panel.onState=value=>{panel.state=value;panel.lease.observe(value);};
  panel.send=payload=>new Promise(resolve=>requests.push({action:payload.action,resolve}));
  return {panel,requests,pulses};
}
(async()=>{
  let {panel,requests,pulses}=testPanel();
  const start=panel.submit("position");
  const stop=panel.submit("stop");
  assert.equal(requests.length,2,"STOP is clickable while START is pending");
  requests[1].resolve(accepted("stop",21));await stop;
  requests[0].resolve(accepted());await start;
  assert.deepEqual(pulses,[],"Late successful START after STOP cannot rearm");
  ({panel,requests,pulses}=testPanel());
  const pending=panel.submit("position");panel.lease.observe({connected:false});
  requests[0].resolve(accepted());await pending;
  assert.deepEqual(pulses,[],"Disconnect invalidates pre-request token");
  ({panel,requests,pulses}=testPanel());
  const delayed=panel.submit("calibrate");
  panel.lease.observe({...accepted(),closed_loop:{...accepted().closed_loop,state:"READY",run_id:0}});
  requests[0].resolve(accepted("calibrate"));await delayed;
  assert.deepEqual(pulses,[],"Terminal status before HTTP response prevents ownership");
  ({panel,requests,pulses}=testPanel());
  const own=panel.submit("position");requests[0].resolve(accepted());await own;
  assert.deepEqual(pulses,[20]);panel.lease.clear();
  console.log("Closed-loop panel request lifecycle tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
