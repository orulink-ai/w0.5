import assert from 'node:assert/strict';
import * as THREE from '../encoder_dashboard/static/vendor/three/three.module.min.js';
import {createEyeDisplay} from '../encoder_dashboard/static/robot-eyes.js';
let renders=0,timers=0;const heights=[];const eyePositions=[];
const gradient={addColorStop(){}};
const context=new Proxy({roundRect:(x,y,w,h)=>{if(w===204){heights.push(h);eyePositions.push([x,y]);}}}, {get(target,key){return key in target ? target[key] : key.startsWith('create') ? ()=>gradient : ()=>{};},set(target,key,value){target[key]=value;return true;}});
globalThis.document={createElement:()=>({width:0,height:0,getContext:()=>context})};
globalThis.window={matchMedia:()=>({matches:false})};
const originalTimer=globalThis.setTimeout;globalThis.setTimeout=()=>{timers++;return 1;};
try {
  const eyes=createEyeDisplay(THREE,()=>renders++,{animationDriven:true});
  assert.equal(timers,0,'scene-driven eyes must never start an independent random timer');
  eyes.userData.setMotionOpenness(0.2);assert.equal(heights.at(-1),44);
  const count=renders;eyes.userData.setMotionOpenness(0.2);assert.equal(renders,count,'same frame must not redraw a different expression');
  eyes.userData.setMotionOpenness(1);assert.equal(heights.at(-1),220);
  eyes.userData.setMotionOpenness(0);assert.equal(heights.at(-1),18);
  eyes.userData.setMotionExpression({blink:1,gazeX:-0.9,gazeY:-0.15});
  assert.equal(eyePositions.at(-1)[0],556,'gaze visibly shifts toward the partner');
  const expressionRenders=renders;
  eyes.userData.setMotionExpression({blink:1,gazeX:-0.9,gazeY:-0.15});
  assert.equal(renders,expressionRenders,'seeking the same expression is deterministic');
  eyes.userData.setMotionExpression({blink:0,gazeX:NaN,gazeY:Infinity});
  assert.equal(heights.at(-1),18);
  assert.equal(eyePositions.at(-1)[0],610,'invalid gaze is reset to center');
  eyes.userData.stop();eyes.geometry.dispose();eyes.material.map.dispose();eyes.material.dispose();
} finally {globalThis.setTimeout=originalTimer;}
console.log('Deterministic scene-driven eyes tests passed');
