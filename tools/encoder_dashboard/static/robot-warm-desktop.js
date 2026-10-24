/** Warm oak alternative. Dimensions are millimetres; the desktop uses Z-up. */
export function createWarmDesktopScene(THREE) {
  const group = new THREE.Group();
  group.name = 'warm-desktop-scene';
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  let pairMode = true;
  const finish = (options) => {
    const material = new THREE.MeshStandardMaterial(options);
    materials.add(material);
    return material;
  };
  const mesh = (name, geometry, material, parent = group) => {
    geometries.add(geometry);
    const value = new THREE.Mesh(geometry, material);
    value.name = name;
    value.castShadow = true;
    value.receiveShadow = true;
    parent.add(value);
    return value;
  };
  const box = (name, size, position, material, parent) => {
    const value = mesh(name, new THREE.BoxGeometry(...size), material, parent);
    value.position.set(...position);
    return value;
  };
  const oakTexture = makeOakTexture(THREE);
  textures.add(oakTexture);
  const oak = finish({color:0xe1c49d, map:oakTexture, roughness:0.72});
  const oakEdge = finish({color:0xb58b5e, map:oakTexture, roughness:0.76});
  const ceramic = finish({color:0xe9e3d6, roughness:0.3, metalness:0.02});
  const sage = finish({color:0x667567, roughness:0.96});
  const paper = finish({color:0xe5dfcc, roughness:0.94});
  const graphite = finish({color:0x363d36, roughness:0.85});
  const brass = finish({color:0xa68b5b, metalness:0.6, roughness:0.35});
  const coffee = finish({color:0x26140e, roughness:0.23});
  const soil = finish({color:0x332c21, roughness:1});
  const leaves = [0x536b45, 0x6e8056, 0x3f5b3b].map((color) => finish({color, roughness:0.75}));
  const stemMaterial = finish({color:0x65714b, roughness:0.88});
  const table = box('warm-solid-oak-desktop', [900, 700, 16], [0, 70, -8], [oakEdge, oakEdge, oakEdge, oakEdge, oak, oakEdge]);
  table.castShadow = false;

  const notebook = new THREE.Group();
  notebook.name = 'sage-linen-notebook';
  notebook.position.set(-202, 32, 0);
  notebook.rotation.z = -0.14;
  group.add(notebook);
  box('notebook-lower-cover', [90, 140, 1.2], [0, 0, 0.6], sage, notebook);
  box('notebook-paper-block', [87, 137, 9], [0.7, 0, 5.6], paper, notebook);
  box('notebook-upper-cover', [90, 140, 1.2], [0, 0, 10.6], sage, notebook);
  box('notebook-spine', [2.4, 140, 10], [-44, 0, 5.2], sage, notebook);
  box('notebook-elastic', [1.8, 140.3, 0.4], [33, 0, 11.4], graphite, notebook);
  box('notebook-title-line', [22, 0.4, 0.16], [-12, -39, 11.3], brass, notebook);
  const pencil = new THREE.Group();
  pencil.name = 'full-size-graphite-pencil';
  pencil.position.set(-4, 0, 14);
  pencil.rotation.z = 0.19;
  notebook.add(pencil);
  mesh('pencil-hexagonal-barrel', new THREE.CylinderGeometry(3, 3, 125, 6), graphite, pencil);
  const woodTip = mesh('pencil-sharpened-wood', new THREE.ConeGeometry(3, 12, 6), oakEdge, pencil);
  woodTip.rotation.z = Math.PI;
  woodTip.position.y = -68.5;
  const lead = mesh('pencil-graphite-tip', new THREE.ConeGeometry(0.8, 3, 6), graphite, pencil);
  lead.rotation.z = Math.PI;
  lead.position.y = -75;

  const mug = new THREE.Group();
  mug.name = 'ivory-coffee-mug';
  mug.position.set(190, 45, 0);
  mug.rotation.z = -0.22;
  group.add(mug);
  const saucer = mesh('ceramic-saucer', new THREE.CylinderGeometry(55, 53, 4, 64), ceramic, mug);
  saucer.rotation.x = Math.PI / 2;
  saucer.position.z = 2;
  const profile = [
    [0, 4], [31, 4], [34, 5], [35, 10], [39.5, 85], [40, 90],
    [39.4, 92], [37.7, 92.4], [36, 90.5], [35.8, 85], [31, 14], [28, 10], [0, 10],
  ].map(([radius, height]) => new THREE.Vector2(radius, height));
  const vessel = mesh('open-ceramic-mug', new THREE.LatheGeometry(profile, 64), ceramic, mug);
  vessel.rotation.x = Math.PI / 2;
  const handle = mesh('mug-handle', new THREE.TorusGeometry(19, 4.5, 12, 40), ceramic, mug);
  handle.rotation.x = Math.PI / 2;
  handle.scale.set(0.86, 1.16, 1);
  handle.position.set(43, 0, 49);
  const liquid = mesh('coffee-surface', new THREE.CircleGeometry(35, 64), coffee, mug);
  liquid.position.z = 81;
  liquid.castShadow = false;

  const plant = new THREE.Group();
  plant.name = 'small-desk-plant';
  plant.position.set(-177, 190, 0);
  group.add(plant);
  const planterProfile = [[0,0], [23,0], [24,2], [30,43], [30,46], [27.5,46], [26,40], [21,5], [0,5]]
    .map(([radius,height]) => new THREE.Vector2(radius,height));
  const planter = mesh('matte-ceramic-planter', new THREE.LatheGeometry(planterProfile, 48), ceramic, plant);
  planter.rotation.x = Math.PI / 2;
  const earth = mesh('planter-soil', new THREE.CircleGeometry(26, 48), soil, plant);
  earth.position.z = 41;
  const shoots = [
    [-18,0,96,0.3], [21,9,113,2.6], [-10,17,128,1.3],
    [10,-15,95,-0.8], [-24,-11,73,3.5], [25,0,76,0.4],
    [0,6,140,2.1], [4,-6,120,-1.6],
  ];
  shoots.forEach(([x,y,z,angle], index) => {
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0,0,41), new THREE.Vector3(x*0.3,y*0.4,z*0.65), new THREE.Vector3(x,y,z),
    ]);
    mesh(`plant-stem-${index}`, new THREE.TubeGeometry(curve, 12, 0.8, 5, false), stemMaterial, plant);
    const leaf = mesh(`plant-leaf-${index}`, new THREE.SphereGeometry(1, 16, 10), leaves[index % leaves.length], plant);
    leaf.position.set(x,y,z-3);
    leaf.scale.set(8,20,1.3);
    leaf.rotation.set(0.68+(index%3)*0.12,0.25,angle);
    const sideLeaf = mesh(`plant-side-leaf-${index}`, new THREE.SphereGeometry(1, 12, 8), leaves[(index+1)%leaves.length], plant);
    sideLeaf.position.set(x*0.6-4,y*0.6+1,z*0.73);
    sideLeaf.scale.set(5.5,14,1);
    sideLeaf.rotation.set(-0.6,0.4,angle+1.8);
  });

  return {
    group,
    place(bounds) {
      const center = bounds.getCenter(new THREE.Vector3());
      group.position.set(center.x,center.y,bounds.min.z-0.4);
    },
    setPairMode(value) { pairMode = Boolean(value); },
    setVisible(value) { group.visible = Boolean(value); },
    getFramingBounds(bounds) {
      const center = bounds.getCenter(new THREE.Vector3());
      const framing = bounds.clone();
      framing.expandByPoint(new THREE.Vector3(center.x-(pairMode ? 262 : 250),center.y-90,bounds.min.z));
      framing.expandByPoint(new THREE.Vector3(center.x+260,center.y+230,Math.max(bounds.max.z+10,bounds.min.z+150)));
      return framing;
    },
    dispose() {
      group.removeFromParent();
      geometries.forEach((value)=>value.dispose());
      materials.forEach((value)=>value.dispose());
      textures.forEach((value)=>value.dispose());
      geometries.clear();
      materials.clear();
      textures.clear();
      group.clear();
    },
  };
}

function makeOakTexture(THREE) {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 512;
  const context = canvas.getContext('2d');
  context.fillStyle = '#ddd1ba';
  context.fillRect(0,0,1024,512);
  let seed = 731;
  const random = () => {
    seed = (seed*1664525+1013904223)>>>0;
    return seed/4294967296;
  };
  for (let line=0;line<1250;line+=1) {
    const y = random()*512;
    const amplitude = 0.8+random()*2.8;
    const phase = random()*Math.PI*2;
    context.strokeStyle = `rgba(103,76,43,${0.018+random()*0.055})`;
    context.lineWidth = 0.3+random()*0.65;
    context.beginPath();
    for (let x=0;x<=1024;x+=12) {
      const grainY = y+Math.sin(x/170+phase)*amplitude+Math.sin(x/49+phase)*0.35;
      if (x===0) context.moveTo(x,grainY);
      else context.lineTo(x,grainY);
    }
    context.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2,2);
  texture.anisotropy = 8;
  return texture;
}
