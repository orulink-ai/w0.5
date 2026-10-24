"use strict";
const assert = require("node:assert/strict");
const {viewModel} = require("../encoder_dashboard/static/components/closed-loop.js");
const state = (patch = {}, outer = {}) => ({connected:true, signal:"valid", closed_loop:{supported:true,
  available:true, protocol_version:3, state:"READY", calibrated:true, enabled:false, sensor_valid:true, command:{status:"idle"}, ...patch}, ...outer});
assert.equal(viewModel(state()).ready, true);
assert.equal(viewModel(state({state:"UNCALIBRATED"})).calibrate, true);
assert.equal(viewModel(state({state:"UNCALIBRATED"})).ready, false);
assert.equal(viewModel(state()).calibrate,true,'Stopped calibrated motor may recalibrate');
for(const fault of ['ALIGNMENT_FAILED','FOC_INIT_FAILED','OVERSPEED','SENSOR_INVALID','HARDWARE_OR_FEEDBACK','SOFT_LIMIT','ENABLE_FAILED']) {
  assert.equal(viewModel(state({state:'FAULT',fault})).calibrate,true);
}
for(const patch of [{state:'FAULT',fault:'INIT_FAILED'},{state:'FAULT',fault:'WATCHDOG_INIT_FAILED'},
  {state:'FAULT',fault:'ALIGNMENT_FAILED',enabled:true},{state:'FAULT',fault:'ALIGNMENT_FAILED',sensor_valid:false}]) {
  assert.equal(viewModel(state(patch)).calibrate,false);
}
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
const diagnostic = state({supported:false,available:false,protocol_version:null}, {encoder_mode:'dual_diagnostic'});
assert.equal(viewModel(diagnostic).visible,true,'Dual diagnostics must retain the original single-motor workstation');
for (const action of ['ready','calibrate','stop','reset','overspeedConfig']) {
  assert.equal(Boolean(viewModel(diagnostic)[action]),false,'Diagnostic firmware cannot execute motor commands');
}
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
assert.equal(viewModel(state({protocol_version:4})).ready,true);
assert.equal(viewModel(state({protocol_version:4,state:"UNCALIBRATED"})).calibrate,true);
assert.equal(viewModel(state({state:"FAULT",fault:"OVERSPEED"})).reset,true);
assert.equal(viewModel(state({protocol_version:4,state:"FAULT",fault:"OVERSPEED"})).reset,true);
for (const patch of [{state:"READY",fault:"OVERSPEED"}, {state:"FAULT",fault:"SENSOR_INVALID"},
  {state:"FAULT",fault:"OVERSPEED",enabled:true}, {state:"FAULT",fault:"OVERSPEED",sensor_valid:false},
  {state:"FAULT",fault:"OVERSPEED",available:false}, {state:"FAULT",fault:"OVERSPEED",protocol_version:2}]) {
  assert.equal(viewModel(state(patch)).reset,false,"only a fresh stopped overspeed fault can reset");
}
assert.equal(viewModel(state({state:"FAULT",fault:"OVERSPEED"}),true).reset,false);
assert.equal(viewModel(state({state:"FAULT",fault:"OVERSPEED"}),false).ready,false);
assert.equal(viewModel(state({overspeed_enabled:true})).overspeedConfig,true);
assert.equal(viewModel(state({protocol_version:4,overspeed_enabled:true})).overspeedConfig,true);
assert.equal(viewModel(state({overspeed_enabled:false})).overspeedConfig,true);
assert.equal(viewModel(state()).overspeedConfig,false,"old firmware has no confirmed switch state");
assert.equal(viewModel(state({state:"RUNNING",enabled:true,overspeed_enabled:true})).overspeedConfig,false);
assert.equal(viewModel(state({state:"FAULT",fault:"OVERSPEED",overspeed_enabled:true})).overspeedConfig,true);
assert.equal(viewModel(state({state:"FAULT",fault:"SENSOR_INVALID",overspeed_enabled:true})).overspeedConfig,false);
assert.equal(viewModel(state({overspeed_enabled:true}),true).overspeedConfig,false);
const {ClosedLoopPanel:PayloadPanel}=require("../encoder_dashboard/static/components/closed-loop.js");
assert.deepEqual(PayloadPanel.prototype.payload.call({state:state({overspeed_enabled:true})},"overspeed"),
  {action:"overspeed",enabled:false});
assert.deepEqual(PayloadPanel.prototype.payload.call({state:state({overspeed_enabled:false})},"overspeed"),
  {action:"overspeed",enabled:true});

const positionInputs = {target_deg:{value:"0"},target_range:{value:"0"}};
const edits=[];
const positionPanel = {state:state({soft_min_deg:-45,soft_max_deg:60}), input:name=>positionInputs[name],
  livePosition:{input:value=>edits.push(["input",value]),release:value=>edits.push(["release",value])}};
PayloadPanel.prototype.setPositionValue.call(positionPanel,30);
assert.equal(positionInputs.target_deg.value,"30");assert.equal(positionInputs.target_range.value,"30");
PayloadPanel.prototype.setPositionValue.call(positionPanel,90,true);
assert.equal(positionInputs.target_deg.value,"60");assert.deepEqual(edits,[["input",30],["release",60]]);
PayloadPanel.prototype.setPositionValue.call(positionPanel,NaN);
assert.equal(edits.length,2,"Transient blank number edits do not send invalid targets");

const speedInputs = {target_deg:{value:"30"},speed_rpm:{value:"10"},rpm:{value:"-10"}};
const speedPanel = {input:name=>speedInputs[name]};
assert.deepEqual(PayloadPanel.prototype.payload.call(speedPanel,"position"),
  {action:"position",target_deg:30,speed_rpm:10});
assert.deepEqual(PayloadPanel.prototype.payload.call(speedPanel,"velocity"),{action:"velocity",rpm:-10});

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
  ({panel,requests,pulses}=testPanel());
  const resetting=panel.submit("reset");requests[0].resolve(accepted("reset"));await resetting;
  assert.deepEqual(pulses,[],"RESET cannot acquire a motion lease");
  ({panel,requests,pulses}=testPanel());
  const switching=panel.submit("overspeed");requests[0].resolve(accepted("overspeed"));await switching;
  assert.deepEqual(pulses,[],"Configuring protection cannot acquire a motion lease");
  console.log("Closed-loop panel request lifecycle tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
