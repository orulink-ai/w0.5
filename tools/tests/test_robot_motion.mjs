import assert from 'node:assert/strict';
import { MOTION_DURATION, MOTION_KEY_TIMES, sampleRobotMotion } from '../encoder_dashboard/static/robot-motion.mjs';

const radians = degrees => degrees * Math.PI / 180;
const close = (a, b, tolerance = 1e-9) => assert.ok(Math.abs(a - b) <= tolerance, `${a} ≠ ${b}`);
assert.equal(MOTION_DURATION, 18);
for (const model of ['camera', 'screen']) {
  for (const paired of [true, false]) {
    for (let i = -3600; i <= 7200; i++) {
      const time = i / 100;
      const pose = sampleRobotMotion(time, model, paired);
      assert.ok(Number.isFinite(pose.yaw) && Number.isFinite(pose.pitch));
      assert.ok(Math.abs(pose.yaw) <= radians(50) + 1e-10);
      assert.ok(Math.abs(pose.pitch) <= radians(22) + 1e-10);
      assert.ok(pose.blink >= 0 && pose.blink <= 1);
      assert.equal(typeof pose.phase, 'string');
      const nextLoop = sampleRobotMotion(time + MOTION_DURATION, model, paired);
      close(pose.yaw, nextLoop.yaw);
      close(pose.pitch, nextLoop.pitch);
    }
    const origin = sampleRobotMotion(0, model, paired);
    assert.equal(origin.yaw, 0);
    assert.equal(origin.pitch, 0);
    assert.deepEqual(sampleRobotMotion(MOTION_DURATION, model, paired), origin);
    const h = 1e-4;
    const before = sampleRobotMotion(MOTION_DURATION - h, model, paired);
    const after = sampleRobotMotion(h, model, paired);
    close(before.yaw, after.yaw, 1e-7);
    close(before.pitch, after.pitch, 1e-7);
    close((origin.yaw - before.yaw) / h, (after.yaw - origin.yaw) / h, 1e-4);
    close((origin.pitch - before.pitch) / h, (after.pitch - origin.pitch) / h, 1e-4);
  }
}
// Readability: a held look, a delayed reply and two separate viewer nods.
for (const model of ['camera', 'screen']) {
  const sign = model === 'camera' ? 1 : -1;
  assert.ok(sign * sampleRobotMotion(2.2, model).yaw < radians(-30), 'observation must visibly turn outward');
  close(sampleRobotMotion(2.1, model).yaw, sampleRobotMotion(2.3, model).yaw);
  assert.ok(sign * sampleRobotMotion(6.1, model).yaw > radians(45), 'hold a clear inward look before greeting');
  assert.ok(sampleRobotMotion(11.9, model).pitch > radians(11), 'first viewer nod is legible');
  close(sampleRobotMotion(13, model).pitch, 0);
  assert.ok(sampleRobotMotion(13.7, model).pitch > radians(17), 'second nod is distinct and stronger');
}
assert.ok(sampleRobotMotion(6.9, 'camera').pitch > radians(17));
close(sampleRobotMotion(6.9, 'screen').pitch, 0);
assert.ok(sampleRobotMotion(7.8, 'screen').pitch > radians(19));
close(sampleRobotMotion(7.8, 'camera').pitch, 0);
for (const time of [1, 4, 8, 9.5, 10.5, 13, 17]) {
  assert.deepEqual(sampleRobotMotion(time, 'camera', false), sampleRobotMotion(time, 'screen', false));
}
assert.ok(sampleRobotMotion(5.1, 'screen').gazeX < -0.5, 'eyes lead the inward head turn');
for (const badTime of [NaN, Infinity, -Infinity, undefined]) {
  assert.deepEqual(sampleRobotMotion(badTime, 'screen'), sampleRobotMotion(0, 'screen'));
}
console.log('Robot gesture amplitude, held looks, delayed reply, separate nods and deterministic loops passed');

// Preserve smooth starts/stops without weakening the readable gesture amplitude.
const h=1e-4;
for(const model of ['camera','screen']) {
  for(const time of MOTION_KEY_TIMES) {
    for(const axis of ['yaw','pitch','blink','gazeX','gazeY']) {
      const at=offset=>sampleRobotMotion(time+offset,model)[axis];
      const left=(3*at(0)-4*at(-h)+at(-2*h))/(2*h);
      const right=(-3*at(0)+4*at(h)-at(2*h))/(2*h);
      close(left,right,0.003);
      const leftAcceleration=(2*at(0)-5*at(-h)+4*at(-2*h)-at(-3*h))/h**2;
      const rightAcceleration=(2*at(0)-5*at(h)+4*at(2*h)-at(3*h))/h**2;
      close(leftAcceleration,rightAcceleration,0.2);
    }
  }
}
console.log('Gesture and eye channels have continuous velocity/acceleration at all boundaries');
