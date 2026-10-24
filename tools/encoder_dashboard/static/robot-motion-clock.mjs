/** One frame loop with a retained cadence remainder and a seekable scene clock. */
export function createMotionClock({onFrame, onState = () => {}, requestFrame = requestAnimationFrame,
  cancelFrame = cancelAnimationFrame, now = () => performance.now(), fps = 24}) {
  let elapsed=0, requested=false, active=false, disposed=false, frame=null, last=now(), remainder=0;
  const interval=1000/fps;
  const state=() => ({playing:requested && active && !disposed,intent:requested,time:elapsed});
  function cancel() {if(frame!==null)cancelFrame(frame);frame=null;}
  function tick(timestamp) {
    frame=null;
    if (!state().playing) return;
    const delta=Math.max(timestamp-last,0);
    elapsed+=delta/1000;
    remainder+=delta;
    last=timestamp;
    if (remainder+1e-6>=interval) {
      remainder=Math.max(0,remainder-Math.floor((remainder+1e-6)/interval)*interval);
      onFrame(elapsed);
    }
    if(state().playing)frame=requestFrame(tick);
  }
  function sync() {
    if(state().playing && frame===null) {last=now();remainder=0;frame=requestFrame(tick);}
    if(!state().playing)cancel();
    onState(state());
  }
  function seek(value) {
    if(disposed)return;
    requested=false;cancel();elapsed=Number.isFinite(value) ? Math.max(0,value) : 0;
    last=now();remainder=0;onFrame(elapsed);onState(state());
  }
  return {
    get time(){return elapsed;},
    get playing(){return state().playing;},
    get intent(){return requested;},
    play(){if(disposed)return;requested=true;sync();},
    pause(){requested=false;cancel();onFrame(elapsed);onState(state());},
    setActive(value){active=Boolean(value);sync();},
    seek,
    reset:()=>seek(0),
    dispose(){requested=false;active=false;disposed=true;cancel();onState(state());},
  };
}
