import assert from 'node:assert/strict';
import { finishForPart, appearanceForPart } from '../encoder_dashboard/static/robot-finishes.mjs';
for (const model of ['camera','screen']) {
  assert.equal(finishForPart(model, 2).role, 'motor');
  assert.equal(finishForPart(model, 7).role, 'motor');
  assert.equal(finishForPart(model, 4).role, 'shell');
}
assert.equal(finishForPart('screen', 10).role, 'display');
assert.equal(finishForPart('screen', 11).role, 'shell');
assert.equal(finishForPart('camera', 12).role, 'lens');
const display = appearanceForPart('screen', 10, 'studio', false, false);
const highlighted = appearanceForPart('screen', 10, 'studio', true, true);
assert.notEqual(display.emissive, '#000000');
assert.notEqual(highlighted.color, display.color);
assert.equal(highlighted.opacity, 1);
const reset = appearanceForPart('screen', 10, 'studio', false, false);
assert.deepEqual(reset, display, 'selection must not destroy original glass/emission settings');
assert.equal(appearanceForPart('camera', 13, 'studio', false, true).depthWrite, false);
assert.equal(appearanceForPart('camera', 13, 'studio', false, false).depthWrite, true);
assert.equal(appearanceForPart('camera', 13, 'cad', false, false).color, null);
assert.equal(appearanceForPart('screen', 10, 'cad', false, false).emissiveIntensity, 0);
console.log('Robot material role and appearance tests passed');
