import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from '../encoder_dashboard/static/vendor/three/three.module.min.js';
import {createRobotRig} from '../encoder_dashboard/static/robot-rig.js';
for (const stem of ['robot','robot-screen']) {
  const manifest=JSON.parse(fs.readFileSync(new URL(`../encoder_dashboard/static/models/${stem}.json`,import.meta.url)));
  const parent=new THREE.Group();
  const meshes=manifest.meshes.map((part,index)=>{
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1));
    mesh.name=String(index);parent.add(mesh);return mesh;
  });
  const rig=createRobotRig(THREE,parent,meshes,manifest);
  const point=(index)=>meshes[index].localToWorld(new THREE.Vector3(30,20,80));
  rig.apply({yaw:0,pitch:0});
  meshes.forEach((_mesh,i)=>assert.ok(point(i).distanceTo(new THREE.Vector3(30,20,80))<1e-8,'rest pose must preserve original CAD coordinates'));
  const base=point(0), motor=point(2), support=point(7), head=point(10);
  rig.apply({yaw:0,pitch:0.1});
  assert.ok(point(0).distanceTo(base)<1e-8);
  assert.ok(point(2).distanceTo(motor)<1e-8);
  assert.ok(point(7).distanceTo(support)<1e-8,'pitch must not rotate its supporting motor');
  assert.ok(point(10).distanceTo(head)>0.1,'display/camera should pitch with head');
  rig.apply({yaw:0.2,pitch:0});
  assert.ok(point(2).distanceTo(motor)<1e-8,'yaw motor body remains on base');
  assert.ok(point(7).distanceTo(support)>0.1,'upper motor follows yaw');
  const eye=new THREE.Object3D();eye.position.set(33,15,81);rig.attachHead(eye);
  rig.apply({yaw:0,pitch:0});
  assert.ok(eye.getWorldPosition(new THREE.Vector3()).distanceTo(new THREE.Vector3(33,15,81))<1e-8);
  const offset=eye.getWorldPosition(new THREE.Vector3()).distanceTo(point(10));
  rig.apply({yaw:-0.15,pitch:0.1});
  assert.ok(Math.abs(eye.getWorldPosition(new THREE.Vector3()).distanceTo(point(10))-offset)<1e-8,'eye texture must stay attached to moving screen');
  rig.reset();assert.ok(point(10).distanceTo(head)<1e-8);
}
console.log('Robot two-axis rig tests passed');
