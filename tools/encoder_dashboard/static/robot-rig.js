/** Reparent baked CAD coordinates around the two measured joint axes. */
export function createRobotRig(THREE, parent, meshes, manifest) {
  const yaw = manifest.joints.find(joint => joint.id === 'yaw');
  const pitch = manifest.joints.find(joint => joint.id === 'pitch');
  if (!yaw || !pitch) throw new Error('模型缺少双轴定义');
  const yawOrigin = new THREE.Vector3(...yaw.origin);
  const pitchOrigin = new THREE.Vector3(...pitch.origin);
  const yawAxis = new THREE.Vector3(...yaw.axis).normalize();
  const pitchAxis = new THREE.Vector3(...pitch.axis).normalize();
  const yawPivot = new THREE.Group();yawPivot.name='yaw-pivot';
  yawPivot.position.copy(yawOrigin);parent.add(yawPivot);
  const pitchPivot = new THREE.Group();pitchPivot.name='pitch-pivot';
  pitchPivot.position.copy(pitchOrigin).sub(yawOrigin);yawPivot.add(pitchPivot);
  // Both verified STEP variants share base 0..6, upper support 3/7/8,
  // and rotating head clamp 9 plus camera/screen/head 10 onward.
  meshes.forEach((mesh,index) => {
    if (index >= 9) {pitchPivot.add(mesh);mesh.position.copy(pitchOrigin).negate();}
    else if ([3,7,8].includes(index)) {yawPivot.add(mesh);mesh.position.copy(yawOrigin).negate();}
  });
  const apply = ({yaw: yawAngle = 0,pitch: pitchAngle = 0}) => {
    yawPivot.quaternion.setFromAxisAngle(yawAxis,Number.isFinite(yawAngle) ? yawAngle : 0);
    pitchPivot.quaternion.setFromAxisAngle(pitchAxis,Number.isFinite(pitchAngle) ? pitchAngle : 0);
  };
  return {
    apply,
    reset:() => apply({yaw:0,pitch:0}),
    attachHead(object) {pitchPivot.add(object);object.position.sub(pitchOrigin);},
  };
}
