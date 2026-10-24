import assert from 'node:assert/strict';
import * as THREE from '../encoder_dashboard/static/vendor/three/three.module.min.js';
import {createDesktopScene} from '../encoder_dashboard/static/robot-desktop.js';
import {createWarmDesktopScene} from '../encoder_dashboard/static/robot-warm-desktop.js';
import {getSceneConfig} from '../encoder_dashboard/static/robot-scene-config.mjs';

// Canvas drawing is irrelevant here; test real Three.js world-space geometry.
const gradient = {addColorStop(){}};
const context = new Proxy({}, {get(_target,key) {return key === 'createLinearGradient' || key === 'createRadialGradient' ? () => gradient : () => {};},set(){return true;}});
globalThis.document = {createElement:() => ({width:0,height:0,getContext:() => context})};
const scene = createDesktopScene(THREE);
function size(name) {
  scene.group.updateMatrixWorld(true);
  return new THREE.Box3().setFromObject(scene.group.getObjectByName(name)).getSize(new THREE.Vector3());
}
const keyboard = size('compact-silver-keyboard');
assert.ok(keyboard.x >= 280 && keyboard.x <= 330, 'keyboard should be about 30cm wide');
const mouse = size('silver-wireless-mouse');
assert.ok(mouse.y >= 100 && mouse.y <= 125, 'mouse should be about 11cm long');
const monitor = size('wide-monitor');
assert.ok(monitor.x >= 580 && monitor.x <= 650, '27-inch-class monitor should be about 60cm wide');
assert.ok(monitor.z >= 420 && monitor.z <= 500, 'monitor height includes its stand');
const bounds = new THREE.Box3(new THREE.Vector3(-14,-2,-4),new THREE.Vector3(81,79,104));
for (const decor of [scene,createWarmDesktopScene(THREE)]) {
  decor.place(bounds);
  assert.equal(decor.group.position.z,-4.4,'desk top must stay just below CAD feet');
  decor.setPairMode(true);
  assert.ok(decor.getFramingBounds(bounds).containsBox(bounds));
  decor.setVisible(false);
  assert.equal(decor.group.visible,false);
  decor.dispose();
  assert.equal(decor.group.children.length,0);
}
assert.equal(getSceneConfig('warm-pair').theme,'warm');
assert.equal(getSceneConfig('warm-pair').paired,true);
assert.equal(getSceneConfig('warm-desk').paired,false);
assert.equal(getSceneConfig('studio').theme,'studio');
assert.equal(getSceneConfig('invalid').theme,'tech');
console.log('Robot scene scale, switching and resource tests passed');
