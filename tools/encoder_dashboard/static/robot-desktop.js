/** A millimetre-scale, Z-up workspace with original procedural screen artwork. */
export function createDesktopScene(THREE) {
  const group = new THREE.Group();
  group.name = 'desktop-scene';
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  let pairMode = true;
  const geometry = (value) => { geometries.add(value); return value; };
  const finish = (options) => {
    const value = new THREE.MeshStandardMaterial(options);
    materials.add(value);
    return value;
  };
  const mesh = (name, shape, material, parent = group) => {
    const value = new THREE.Mesh(geometry(shape), material);
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
  const graphite = finish({ color: 0x343a3c, metalness: 0.2, roughness: 0.6 });
  const edge = finish({ color: 0x1d2427, metalness: 0.55, roughness: 0.38 });
  const black = finish({ color: 0x101619, metalness: 0.45, roughness: 0.36 });
  const silver = finish({ color: 0xaeb9be, metalness: 0.78, roughness: 0.32 });
  const keys = finish({ color: 0xc3cbd0, metalness: 0.12, roughness: 0.52 });
  const warmWhite = finish({ color: 0xffe3b7, emissive: 0xffc681, emissiveIntensity: 1.3, roughness: 0.4 });
  const tabletop = mesh('graphite-worktop', new THREE.BoxGeometry(1100, 750, 14), [edge, edge, edge, edge, graphite, edge]);
  tabletop.position.set(0, 15, -7);
  tabletop.castShadow = false;
  box('desk-front-silver-reveal', [1098, 1.2, 1.2], [0, -360.4, -2.3], silver);

  const wallMaterial = finish({ color: 0x33383b, roughness: 0.98 });
  const wall = mesh('charcoal-back-wall', new THREE.PlaneGeometry(1400, 850), wallMaterial);
  wall.rotation.x = Math.PI / 2;
  wall.position.set(0, 350, 340);
  wall.castShadow = false;
  wall.receiveShadow = false;

  const monitor = new THREE.Group();
  monitor.name = 'wide-monitor';
  monitor.position.set(-160, 230, 0);
  monitor.scale.setScalar(1.5); // 606 mm wide, 454 mm high including stand.
  group.add(monitor);
  box('monitor-thin-aluminum-frame', [404, 9, 229], [0, 0, 188], black, monitor);
  box('monitor-rear-housing', [365, 7, 185], [0, 7, 188], edge, monitor);
  box('monitor-lower-bezel', [401, 1.5, 4], [0, -5.2, 76], black, monitor);
  const artwork = createWallpaper(THREE);
  textures.add(artwork);
  const displayMaterial = new THREE.MeshBasicMaterial({map: artwork, toneMapped: false});
  materials.add(displayMaterial);
  const display = mesh('original-cyan-flow-wallpaper', new THREE.PlaneGeometry(392, 218), displayMaterial, monitor);
  display.rotation.x = Math.PI / 2;
  display.position.set(0, -5.3, 189);
  display.castShadow = false;
  display.receiveShadow = false;
  const indicatorMaterial = finish({color:0xb9dbdb, emissive:0x87aeb7, emissiveIntensity:0.7});
  box('monitor-status-light', [1.4, 0.5, 0.65], [181, -5.7, 76.5], indicatorMaterial, monitor);
  box('monitor-stand-base', [145, 110, 5], [16, -4, 2.5], black, monitor);
  const stem = box('monitor-stand-stem', [20, 18, 80], [18, 13, 43], black, monitor);
  stem.rotation.y = -0.14;
  box('monitor-stand-joint', [55, 13, 30], [10, 15, 82], black, monitor);

  // The keyboard stays outside the robots' central working area.
  const keyboard = new THREE.Group();
  keyboard.name = 'compact-silver-keyboard';
  keyboard.position.set(-290, -74, 0);
  keyboard.scale.setScalar(1.4); // About 308 x 106 mm.
  keyboard.rotation.z = -0.06;
  group.add(keyboard);
  box('keyboard-silver-case', [220, 76, 7], [0, 0, 3.5], silver, keyboard);
  box('keyboard-dark-keybed', [214, 69, 1], [0, 0, 7.2], edge, keyboard);
  const layout = [13, 13, 12, 11, 8];
  const keyCount = layout.reduce((sum, count) => sum + count, 0);
  const keyGeometry = geometry(new THREE.BoxGeometry(13.3, 10.6, 2.5));
  const keyInstances = new THREE.InstancedMesh(keyGeometry, keys, keyCount);
  keyInstances.name = 'keyboard-keycaps';
  keyInstances.castShadow = true;
  keyInstances.receiveShadow = true;
  const transform = new THREE.Object3D();
  let keyIndex = 0;
  layout.forEach((count, row) => {
    for (let column = 0; column < count; column += 1) {
      transform.position.set(-98 + column * 16 + (row > 1 ? (row - 1) * 3 : 0), 26 - row * 13, 9.1);
      transform.updateMatrix();
      keyInstances.setMatrixAt(keyIndex++, transform.matrix);
    }
  });
  keyboard.add(keyInstances);
  box('keyboard-space-bar', [67, 10.6, 2.5], [18, -26, 9.1], keys, keyboard);
  const accent = finish({color:0x5a7e89, metalness:0.2, roughness:0.5});
  box('keyboard-escape-key', [13.5, 10.8, 2.8], [-98, 26, 9.25], accent, keyboard);

  const mouse = new THREE.Group();
  mouse.name = 'silver-wireless-mouse';
  mouse.position.set(-85, -125, 0);
  mouse.scale.setScalar(2.2); // About 66 x 106 mm before its slight desk rotation.
  mouse.rotation.z = -0.08;
  group.add(mouse);
  const mouseBody = mesh('mouse-shell', new THREE.SphereGeometry(1, 32, 16), silver, mouse);
  mouseBody.scale.set(15, 24, 9);
  mouseBody.position.z = 6;
  box('mouse-center-seam', [0.38, 18, 0.3], [0, 6, 14.8], edge, mouse);
  const wheel = mesh('mouse-scroll-wheel', new THREE.CylinderGeometry(2.2, 2.2, 3.3, 16), graphite, mouse);
  wheel.rotation.z = Math.PI / 2;
  wheel.position.set(0, 8, 14.5);

  const lamp = new THREE.Group();
  lamp.name = 'slim-task-lamp';
  lamp.position.set(320, 180, 0);
  lamp.scale.setScalar(1.4);
  group.add(lamp);
  const lampBase = mesh('lamp-base', new THREE.CylinderGeometry(32, 34, 6, 48), black, lamp);
  lampBase.rotation.x = Math.PI / 2;
  lampBase.position.z = 3;
  const lampStem = mesh('lamp-stem', new THREE.CylinderGeometry(2.8, 2.8, 260, 16), silver, lamp);
  lampStem.rotation.x = Math.PI / 2;
  lampStem.position.set(8, 8, 134);
  box('lamp-head', [114, 18, 8], [-42, 8, 263], black, lamp);
  box('lamp-warm-diffuser', [101, 12, 0.6], [-42, 8, 258.7], warmWhite, lamp);
  const taskLight = new THREE.PointLight(0xffd8a1, 210000, 600, 2);
  taskLight.name = 'warm-local-task-light';
  taskLight.position.set(260, 190, 345);
  group.add(taskLight);

  // Emissive light wash supplies a soft, stable wall glow without shadow maps.
  const washTexture = createWallGlow(THREE);
  textures.add(washTexture);
  const washMaterial = new THREE.MeshBasicMaterial({map: washTexture, transparent: true, depthWrite: false, toneMapped: false});
  materials.add(washMaterial);
  const wash = mesh('warm-monitor-wall-wash', new THREE.PlaneGeometry(850, 360), washMaterial);
  wash.rotation.x = Math.PI / 2;
  wash.position.set(-70, 349.4, 148);
  wash.castShadow = wash.receiveShadow = false;
  box('concealed-warm-light-strip', [730, 2, 2], [-25, 343, 8], warmWhite);
  const screenFill = new THREE.PointLight(0x78cce7, 23000, 420, 2);
  screenFill.name = 'soft-screen-fill';
  screenFill.position.set(-160, 175, 270);
  group.add(screenFill);

  return {
    group,
    place(bounds) {
      const center = bounds.getCenter(new THREE.Vector3());
      group.position.set(center.x, center.y, bounds.min.z - 0.4);
    },
    setPairMode(value) { pairMode = Boolean(value); },
    setVisible(value) { group.visible = Boolean(value); },
    getFramingBounds(bounds) {
      const center = bounds.getCenter(new THREE.Vector3());
      const framing = bounds.clone();
      framing.expandByPoint(new THREE.Vector3(center.x - (pairMode ? 480 : 460), center.y - 190, bounds.min.z));
      framing.expandByPoint(new THREE.Vector3(center.x + 370, center.y + 255, Math.max(bounds.max.z + 10, bounds.min.z + 460)));
      return framing;
    },
    dispose() {
      group.removeFromParent();
      keyInstances.dispose();
      geometries.forEach((value) => value.dispose());
      materials.forEach((value) => value.dispose());
      textures.forEach((value) => value.dispose());
      geometries.clear();
      materials.clear();
      textures.clear();
      group.clear();
    },
  };
}

function makeCanvasTexture(THREE, width, height, draw) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext('2d'), width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function createWallpaper(THREE) {
  return makeCanvasTexture(THREE, 1280, 720, (context, width, height) => {
    const background = context.createLinearGradient(0, 0, width, height);
    background.addColorStop(0, '#07101c');
    background.addColorStop(0.55, '#102737');
    background.addColorStop(1, '#07121e');
    context.fillStyle = background;
    context.fillRect(0, 0, width, height);
    // Broad overlapping ribbons create an original fluid, cyan-on-ink artwork.
    for (let index = 0; index < 68; index += 1) {
      const progress = index / 67;
      const ribbon = context.createLinearGradient(0, height, width, 60);
      ribbon.addColorStop(0, `hsla(${195 + progress * 18},85%,${30 + progress * 27}%,0.94)`);
      ribbon.addColorStop(0.46, `hsla(${180 + progress * 12},79%,${55 + progress * 20}%,0.94)`);
      ribbon.addColorStop(1, `hsla(${218 - progress * 15},76%,${25 + progress * 25}%,0.85)`);
      const offset = index * 8;
      context.beginPath();
      context.moveTo(-100, 770 - offset * 0.54);
      context.bezierCurveTo(160 + offset * 0.22, 80 - offset * 0.21, 560 - offset * 0.25, 730 - offset * 0.7, 830, 150 + offset * 0.35);
      context.bezierCurveTo(1090, -15 + offset * 0.3, 1120 + offset * 0.5, 500 - offset * 0.2, 1390, 260 + offset * 0.75);
      context.strokeStyle = ribbon;
      context.lineWidth = 17;
      context.stroke();
      if (index % 4 === 0) {
        context.strokeStyle = 'rgba(184,245,246,0.40)';
        context.lineWidth = 1.3;
        context.stroke();
      }
    }
    const shade = context.createLinearGradient(0, 0, 0, height);
    shade.addColorStop(0, 'rgba(2,8,15,0.5)');
    shade.addColorStop(0.6, 'rgba(2,8,15,0)');
    context.fillStyle = shade;
    context.fillRect(0, 0, width, height);
  });
}

function createWallGlow(THREE) {
  return makeCanvasTexture(THREE, 512, 256, (context, width, height) => {
    const gradient = context.createRadialGradient(width * 0.5, height * 0.8, 0, width * 0.5, height * 0.8, width * 0.48);
    gradient.addColorStop(0, 'rgba(255,187,112,0.30)');
    gradient.addColorStop(0.35, 'rgba(255,177,93,0.16)');
    gradient.addColorStop(1, 'rgba(255,177,93,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
  });
}
