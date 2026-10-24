"use strict";
const assert = require("node:assert/strict");
const {LeaseKeeper} = require("../encoder_dashboard/static/components/lease-keeper.js");
class Clock {
  constructor() { this.tasks = new Map(); this.next = 1; }
  setTimeout(fn) { const id = this.next++; this.tasks.set(id, fn); return id; }
  clearTimeout(id) { this.tasks.delete(id); }
  tick() { const tasks = [...this.tasks.values()]; this.tasks.clear(); for (const fn of tasks) fn(); }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const state = (patch={}) => ({connected:true, closed_loop:{available:true, supported:true,protocol_version:3,
  last_id:20,run_id:20,owned_run_id:20,state:"RUNNING",command:{status:"accepted",action:"position",id:20},...patch}});
(async () => {
  const calls=[], errors=[], clock=new Clock();
  const keeper=new LeaseKeeper({clock,heartbeat:async id=>{calls.push(id);return {ok:true,run_id:id};},onError:e=>errors.push(e)});
  keeper.observe(state()); await flush(); assert.deepEqual(calls,[],"Discovered running state never owns");
  const token=keeper.token(); assert.equal(keeper.accept("position",state(),token),true);
  await flush(); assert.deepEqual(calls,[20]);assert.equal(clock.tasks.size,1);
  clock.tick();await flush();assert.deepEqual(calls,[20,20]);
  keeper.observe(state({last_id:19,run_id:0,state:"READY"}));assert.equal(keeper.runId,20,"Older terminal cannot revoke new ACK");
  keeper.observe(state({run_id:0,state:"READY"}));assert.equal(keeper.runId,null);assert.equal(clock.tasks.size,0);
  assert.equal(keeper.accept("position",state(),keeper.token()),false,"Late HTTP cannot resurrect terminal run");
  let staleToken=keeper.token();keeper.clear();assert.equal(keeper.accept("position",state({last_id:21,run_id:21,owned_run_id:21,
    command:{status:"accepted",action:"position",id:21}}),staleToken),false,"STOP/pagehide invalidates pending START");
  staleToken=keeper.token();keeper.observe({connected:false});
  assert.equal(keeper.accept("position",state(),staleToken),false,"Disconnect invalidates pending ownership");
  assert.equal(keeper.accept("calibrate",state({state:"CALIBRATING",command:{status:"pending",action:"calibrate",id:20}}),keeper.token()),false);
  assert.equal(keeper.accept("velocity",state(),keeper.token()),false,"Matching own action required");
  assert.equal(keeper.accept("position",state({owned_run_id:null}),keeper.token()),false);
  assert.equal(keeper.accept("position",state({protocol_version:1}),keeper.token()),false);
  assert.equal(keeper.accept("position",state({protocol_version:2}),keeper.token()),false);
  assert.equal(keeper.accept("position",state(),keeper.token()),true);await flush();
  keeper.observe(state({last_id:21,run_id:21}));assert.equal(keeper.runId,null,"Another run revokes ownership");
  keeper.observe(state({last_id:25,run_id:25}));
  const pendingBeforeBoot = keeper.token();
  keeper.observe(state({last_id:0,run_id:0,state:"UNCALIBRATED",enabled:false,calibrated:false}));
  assert.equal(keeper.runId,null);
  assert.notEqual(keeper.token(),pendingBeforeBoot,"MCU boot invalidates pending HTTP generation");
  assert.equal(keeper.accept("position",state(),pendingBeforeBoot),false);
  let resolve;
  const slow=new LeaseKeeper({clock,heartbeat:()=>new Promise(done=>{resolve=done;})});
  assert.equal(slow.accept("position",state(),slow.token()),true);clock.tick();assert.equal(clock.tasks.size,0,"Only one heartbeat in flight");
  slow.clear();resolve({ok:true,run_id:20});await flush();assert.equal(clock.tasks.size,0,"Late heartbeat never renews canceled timer");
  const failed=new LeaseKeeper({clock,heartbeat:async()=>{throw new Error("offline");},onError:e=>errors.push(e)});
  failed.accept("position",state(),failed.token());await flush();assert.equal(failed.runId,null);assert.deepEqual(errors,["offline"]);
  const terminal=new LeaseKeeper({clock,heartbeat:async()=>assert.fail("Must not send")});
  terminal.observe(state({state:"READY",run_id:0}));
  assert.equal(terminal.accept("position",state(),terminal.token()),false,"Terminal before HTTP response wins");
  console.log("FOC lease lifecycle tests passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
