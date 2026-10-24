"use strict";
/** Adapt one global UART state to an existing, isolated motor controller UI. */
(function(scope) {
  function motorState(state,motorId) {
    if(motorId===1)return state;
    if(motorId!==2)throw new Error('电机编号只能为 1 或 2');
    const motor=state?.motors?.find(item=>item.id===motorId);
    return {...state,signal:motor?.signal || (state?.connected?'waiting':'disconnected'),
      reading:motor?.reading || null,closed_loop:motor?.closed_loop || {supported:false,available:false},
      encoder_mode:'single'};
  }

  class AdditionalMotorPanel {
    constructor(element,{onState,post,Panel=scope.ClosedLoopUI.ClosedLoopPanel}) {
      this.panel=new Panel(element,{
        title:'电机② · 闭环运动工作台',
        description:'编码器 PB7 · PWM PA6 / PA7 / PB0 · EN PB12 · 独立校准与启停',
        send:async payload=>{
          const full=await post('/api/foc/2',payload);
          onState(full);
          return motorState(full,2);
        },
        // send already published the original full state. Projected state must
        // never replace motor 1 at the global render boundary.
        onState:()=>{},
        heartbeat:runId=>post('/api/foc/2/heartbeat',{run_id:runId}),
      });
    }
    render(state){this.panel.render(motorState(state,2));}
  }
  scope.MotorWorkbench=Object.freeze({motorState,AdditionalMotorPanel});
  if(typeof module!=='undefined')module.exports=scope.MotorWorkbench;
})(globalThis);
