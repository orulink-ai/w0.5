import { createRobotRig } from './robot-rig.js';
import { appearanceForPart } from './robot-finishes.mjs';
import { createEyeDisplay } from './robot-eyes.js';

/** A second complete CAD assembly sharing the viewer's renderer and lighting. */
export function createRobotReplica(THREE, render) {
  const group = new THREE.Group();
  group.name = 'companion-robot';
  let parts = [];
  let eyes;
  let rig;
  let modelId;
  let bounds;
  let visible = true;
  let showEyes = true;
  function clear() {
    eyes?.userData.stop();
    eyes?.material.map.dispose();
    group.traverse((object) => {
      object.geometry?.dispose();
      object.material?.dispose();
    });
    group.clear();
    parts = [];
    eyes = null;
    rig = null;
  }
  function setFinish(mode) {
    parts.forEach((mesh, index) => {
      const appearance = appearanceForPart(modelId,index,mode,false,false);
      mesh.material.color.copy(appearance.color ? new THREE.Color(appearance.color) : mesh.userData.cadColor);
      mesh.material.emissive.set(appearance.emissive);
      for (const key of ['roughness','metalness','clearcoat','clearcoatRoughness','emissiveIntensity']) mesh.material[key] = appearance[key];
      mesh.material.needsUpdate = true;
    });
  }
  return {
    group,
    get bounds() { return bounds; },
    setModel(id, data, mode) {
      clear();
      modelId = id;
      const {manifest, buffer} = data;
      bounds = new THREE.Box3(new THREE.Vector3(...manifest.bounds.min),new THREE.Vector3(...manifest.bounds.max));
      parts = manifest.meshes.map((part) => {
        const geometry = new THREE.BufferGeometry();
        for (const key of ['position','normal']) {
          const range = part[key];
          geometry.setAttribute(key,new THREE.BufferAttribute(new Float32Array(buffer,range.offset,range.count),3));
        }
        geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer,part.index.offset,part.index.count),1));
        const color = new THREE.Color(...part.color);
        const mesh = new THREE.Mesh(geometry,new THREE.MeshPhysicalMaterial({side:THREE.DoubleSide}));
        mesh.userData.cadColor = color;
        mesh.name = part.name;
        mesh.castShadow = mesh.receiveShadow = true;
        group.add(mesh);
        return mesh;
      });
      rig = createRobotRig(THREE,group,parts,manifest);
      if (id === 'screen') {eyes = createEyeDisplay(THREE,render,{animationDriven:true});rig.attachHead(eyes);eyes.visible=visible && showEyes;}
      setFinish(mode);
    },
    setFinish,
    applyPose(pose) {rig?.apply(pose);eyes?.userData.setMotionExpression?.(pose);},
    setEyesEnabled(value) {showEyes=Boolean(value);if(eyes)eyes.visible=visible && showEyes;},
    setVisible(value) {visible=Boolean(value);group.visible=visible;if(eyes)eyes.visible=visible && showEyes;},
    dispose:clear,
  };
}
