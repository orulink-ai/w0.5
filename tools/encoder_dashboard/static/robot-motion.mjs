/** Visual choreography only; these amplitudes are not mechanical limits. */
export const MOTION_DURATION = 18;
const radians = degrees => degrees * Math.PI / 180;
const smootherstep = t => t ** 3 * (10 + t * (-15 + 6 * t));

// Repeated values create readable holds: look, register, then respond.
const CAMERA_YAW = [[0,0],[0.5,0],[1.65,-35],[2.4,-35],[3.65,22],[4.45,22],[5.65,48],[8.9,48],[10,0],[18,0]];
const SCREEN_YAW = [[0,0],[0.85,0],[2,-35],[2.75,-35],[4,22],[4.7,22],[6,48],[8.9,48],[10.3,0],[18,0]];
const CAMERA_LIFT = [[0,0],[0.5,0],[1.65,-8],[2.4,-8],[3.65,0],[18,0]];
const SCREEN_LIFT = [[0,0],[0.85,0],[2,-8],[2.75,-8],[4,0],[18,0]];

// Deliberate downstroke, brief acknowledgement, slower recovery and tiny settle.
function nod(start, amplitude) {
  return [[start,0],[start+0.38,amplitude],[start+0.5,amplitude],
    [start+1.05,-2],[start+1.3,0]];
}
const VIEWER_NODS = [...nod(11.4,12), ...nod(13.2,18)];
const CAMERA_PITCH = [[0,0],...nod(6.4,18),...VIEWER_NODS,[18,0]];
const SCREEN_PITCH = [[0,0],...nod(7.3,20),...VIEWER_NODS,[18,0]];
const GAZE_KEYS = [[0,0],[0.35,0],[0.65,0.8],[2.3,0.8],[2.55,-0.65],
  [4.45,-0.65],[4.8,-0.9],[8.9,-0.9],[9.15,0],[18,0]];
const blinkKeys = start => [[start,1],[start+0.09,0],[start+0.16,0],[start+0.3,1]];
const BLINKS = [blinkKeys(0.1),blinkKeys(10.5),blinkKeys(11.71),blinkKeys(13.51),blinkKeys(16.1)];
const GAZE_Y_KEYS = [[0,0],[11.1,0],[11.4,-0.15],[14.5,-0.15],[14.8,0],[18,0]];
const allTracks = [CAMERA_YAW,SCREEN_YAW,CAMERA_LIFT,SCREEN_LIFT,CAMERA_PITCH,SCREEN_PITCH,GAZE_KEYS,GAZE_Y_KEYS,...BLINKS,blinkKeys(6.71),blinkKeys(7.61)];
export const MOTION_KEY_TIMES = Object.freeze([...new Set(allTracks.flat().map(([time])=>time))].sort((a,b)=>a-b));

function interpolate(time, keys) {
  if (time <= keys[0][0]) return keys[0][1];
  for (let i=1;i<keys.length;i++) {
    const [end,value]=keys[i];
    if(time<=end) {
      const [start,previous]=keys[i-1];
      return previous+(value-previous)*smootherstep((time-start)/(end-start));
    }
  }
  return keys.at(-1)[1];
}

/** Positive yaw looks toward +X; positive pitch lowers the head. Base stays fixed. */
export function sampleRobotMotion(seconds,modelId,paired=true) {
  const time=Number.isFinite(seconds) ? ((seconds%MOTION_DURATION)+MOTION_DURATION)%MOTION_DURATION : 0;
  const replying=paired && modelId==='screen';
  const yaw=interpolate(time,replying ? SCREEN_YAW : CAMERA_YAW)*(replying ? -1 : 1);
  const pitch=interpolate(time,replying ? SCREEN_LIFT : CAMERA_LIFT)
    +interpolate(time,replying ? SCREEN_PITCH : CAMERA_PITCH);
  const greetingBlink=blinkKeys(replying ? 7.61 : 6.71);
  const blink=Math.min(...[...BLINKS,greetingBlink].map(keys=>interpolate(time,keys)));
  const phase=time<0.5 ? '准备观察' : time<4.7 ? '转头观察 · 停住看看'
    : time<6.4 ? (paired ? '转向同伴' : '转向一侧')
      : time<8.9 ? (paired ? (time<7.3 ? '摄像头版先点头' : '屏幕版点头回应') : '点头致意')
        : time<11.4 ? '转回正面 · 看向你' : time<14.5 ? '向你打招呼 · 两次点头' : '回正 · 安静陪伴';
  return {yaw:radians(yaw)||0,pitch:radians(pitch)||0,blink,phase,
    gazeX:replying ? interpolate(time,GAZE_KEYS) : 0,
    gazeY:interpolate(time,GAZE_Y_KEYS)};
}
