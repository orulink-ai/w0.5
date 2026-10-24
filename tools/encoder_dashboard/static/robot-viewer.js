import * as THREE from './vendor/three/three.module.min.js';
import { createRobotRig } from './robot-rig.js';
import { MOTION_DURATION, sampleRobotMotion } from './robot-motion.mjs';
import { createMotionClock } from './robot-motion-clock.mjs';
import { createRobotReplica } from './robot-replica.js';
import { createWarmDesktopScene } from './robot-warm-desktop.js';
import { SCENE_CONFIGS, getSceneConfig } from './robot-scene-config.mjs';
import { createDesktopScene } from './robot-desktop.js';
import { RoomEnvironment } from './vendor/three/RoomEnvironment.js';
import { appearanceForPart } from './robot-finishes.mjs';
import { OrbitControls } from './vendor/three/OrbitControls.js';

import { createEyeDisplay } from './robot-eyes.js';
import { createModelLoader } from './model-loader.mjs';

const MODELS = {
  camera: {label: '摄像头版', title: '小机器人摄像头版本', manifest: '/models/robot.json', binary: '/models/robot.bin'},
  screen: {label: '1.3 寸屏幕版', title: '小机器人 1.3 寸屏幕版本', manifest: '/models/robot-screen.json', binary: '/models/robot-screen.bin'},
};


/** A read-only CAD viewer. Joint markers describe candidates, not live hardware. */
export async function mountRobotViewer(root) {
  if (!root || root.dataset.viewerMounted) return;
  root.dataset.viewerMounted = 'true';
  root.classList.add('robot-viewer');
  root.innerHTML = `
    <header class="rv-header">
      <div><p class="rv-eyebrow">W0.5 / DESKTOP COMPANION</p><h2>小机器人，桌边的新伙伴</h2></div>
      <span class="rv-source-tag">统一尺寸 / mm</span>
    </header>
    <div class="rv-model-toolbar">
      <label for="robot-model-select">模型版本</label>
      <select id="robot-model-select" class="rv-model-select" aria-label="机器人模型版本">
        <option value="camera">摄像头版</option><option value="screen">1.3 寸屏幕版</option>
      </select>
      <label for="robot-scene-select">场景</label>
      <select id="robot-scene-select" class="rv-scene-select" aria-label="机器人场景"><option value="pair">科技桌面 · 双机</option><option value="warm-pair">暖木桌面 · 双机</option><option value="desk">科技桌面 · 单机</option><option value="warm-desk">暖木桌面 · 单机</option><option value="studio">简洁展台</option></select>
      <label for="robot-finish-select">外观</label>
      <select id="robot-finish-select" class="rv-finish-select" aria-label="机器人外观"><option value="studio">暖白材质</option><option value="cad">CAD 原色</option></select>
    </div>
    <div class="rv-layout">
      <div class="rv-stage">
        <div class="rv-canvas" aria-label="机器人三维模型，可拖动旋转、滚轮缩放"></div>
        <div class="rv-stage-top"><span class="rv-model-label"><i></i> 小机器人摄像头版本</span><span class="rv-size"></span></div>
        <div class="rv-loading" role="status">正在载入机器人结构…</div>
        <div class="rv-stage-bottom"><span>拖动旋转 · 滚轮缩放 · 点击查看零件</span><button type="button" class="rv-reset" disabled aria-label="重置机器人视角">↺ <span>重置视角</span></button></div>
      </div>
      <aside class="rv-sidebar" aria-label="机器人结构信息">
        <div class="rv-section-label">两个自由度 <span>2 DOF</span></div>
        <p class="rv-intro">选择电机，透视查看它在装配体中的位置。</p>
        <div class="rv-joints"></div>
        <section class="rv-animation" aria-label="机器人场景动画">
          <div class="rv-section-label">桌边互动 <span>18 s</span></div>
          <p class="rv-motion-phase" role="status" aria-live="polite">准备播放</p>
          <div class="rv-motion-actions"><button type="button" class="rv-motion-toggle" aria-pressed="false" disabled>播放互动</button><button type="button" class="rv-motion-reset" disabled>动作归位</button><button type="button" class="rv-motion-focus" disabled>互动特写</button></div>
          <div class="rv-motion-scrub"><label for="robot-motion-timeline">动作回放</label><output class="rv-motion-time">0.00 / 18.00 s</output></div>
          <input id="robot-motion-timeline" class="rv-motion-timeline" type="range" min="0" max="432" step="1" value="0" aria-label="动画时间轴" disabled>
          <div class="rv-motion-steps"><button type="button" class="rv-motion-prev" disabled aria-label="上一帧">‹ 上一帧</button><output class="rv-motion-frame">0 / 432 帧</output><button type="button" class="rv-motion-next" disabled aria-label="下一帧">下一帧 ›</button></div>
          <p class="rv-motion-note">仅网页动画 · 转头与点头幅度用于视觉预览</p>
        </section>
        <div class="rv-details" aria-live="polite"><span class="rv-detail-kicker">装配体概览</span><h3>真实结构，自由探索</h3><p>正在读取 CAD 装配体与电机位置。</p></div>
        <div class="rv-options">
          <button type="button" class="rv-toggle rv-eyes" aria-pressed="true" hidden><span>屏幕眼睛 · 自动眨眼</span><span class="rv-switch" aria-hidden="true"></span></button>
          <button type="button" class="rv-toggle rv-xray" aria-pressed="false" disabled><span>透视结构</span><span class="rv-switch" aria-hidden="true"></span></button>
          <button type="button" class="rv-toggle rv-axes" aria-pressed="false" disabled><span>显示转轴</span><span class="rv-switch" aria-hidden="true"></span></button>
        </div>
        <p class="rv-note">左右转头 / 俯仰对应关系已确认。轴线按 CAD 外形标注，限位待定。此视图仅展示结构。</p>
      </aside>
    </div>`;

  const canvasHost = root.querySelector('.rv-canvas');
  const loading = root.querySelector('.rv-loading');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  } catch {
    showError(loading, '当前环境无法开启 WebGL，请使用支持三维显示的浏览器。');
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0xece9e2);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.setAttribute('aria-label', '机器人三维装配体');
  canvasHost.append(renderer.domElement);

  const scene = new THREE.Scene();
  const environment = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environmentMap = pmrem.fromScene(environment, 0.04);
  scene.environment = environmentMap.texture;
  scene.environmentIntensity = 0.48;
  environment.dispose();
  pmrem.dispose();
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(2000, 2000),
    new THREE.ShadowMaterial({color:0x68716d, opacity:0.18}));
  floor.receiveShadow = true;
  scene.add(floor);
  const techDesktop = createDesktopScene(THREE);
  const warmDesktop = createWarmDesktopScene(THREE);
  scene.add(techDesktop.group, warmDesktop.group);
  const requestedScene = new URLSearchParams(window.location.search).get('scene');
  let sceneMode = Object.hasOwn(SCENE_CONFIGS, requestedScene) ? requestedScene : 'pair';
  let sceneConfig = getSceneConfig(sceneMode);
  let desktop = sceneConfig.theme === 'warm' ? warmDesktop : techDesktop;
  techDesktop.setVisible(false);
  warmDesktop.setVisible(false);
  root.dataset.scene = sceneMode;
  root.dataset.theme = sceneConfig.theme;
  floor.visible = false;
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 10000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  controls.screenSpacePanning = true;
  controls.maxPolarAngle = Math.PI / 2 - 0.04;
  controls.addEventListener('change', render);
  const hemisphere = new THREE.HemisphereLight(0xc9e0ee, 0x42494c, 0.4);
  scene.add(hemisphere);
  const keyLight = new THREE.DirectionalLight(0xdfeaff, 1.9);
  keyLight.position.set(200, -300, 500);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(2048,2048);
  Object.assign(keyLight.shadow.camera, {left:-500,right:500,top:500,bottom:-500,near:1,far:2000});
  keyLight.shadow.normalBias = 0.25;
  keyLight.shadow.bias = -0.0002;
  keyLight.shadow.radius = 10;
  scene.add(keyLight, keyLight.target);
  const fillLight = new THREE.DirectionalLight(0xa6c8df, 0.65);
  fillLight.position.set(-300, 200, 150);
  scene.add(fillLight);
  const assembly = new THREE.Group();
  const jointAxes = new THREE.Group();
  jointAxes.visible = false;
  const primary = new THREE.Group();
  primary.add(assembly, jointAxes);
  const replica = createRobotReplica(THREE,render);
  scene.add(primary, replica.group);
  const resize = new ResizeObserver(() => {
    const width = Math.max(1, canvasHost.clientWidth);
    const height = Math.max(1, canvasHost.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (fullBounds && !selectedJoint) {
      if(viewMode === 'interaction') frameInteraction();
      else frameOverview();
    }
    else render();
  });
  resize.observe(canvasHost);

  let manifest;
  let primaryRig;
  let motionClock;
  let modelId = 'camera';
  let finishMode = 'studio';
  let eyeDisplay;
  let eyesEnabled = true;
  let selectedJoint = null;
  let xray = false;
  let meshes = [];
  let fullBounds;
  let viewMode = 'overview';
  const details = root.querySelector('.rv-details');

  function render() {
    renderer.render(scene, camera);
  }

  function frame(bounds, reset = false) {
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(bounds.getSize(new THREE.Vector3()).length() / 2, 1);
    const verticalFov = THREE.MathUtils.degToRad(camera.fov);

    const direction = reset || camera.position.distanceTo(controls.target) < 1
      ? (sceneConfig.theme !== 'tech' ? new THREE.Vector3(1.3, -2, 1.1) : new THREE.Vector3(0.75, -2.8, 1.35)).normalize()
      : camera.position.clone().sub(controls.target).normalize();
    // Fit the eight box corners in camera space rather than a bounding sphere.
    const right = new THREE.Vector3().crossVectors(direction, camera.up).normalize();
    const up = new THREE.Vector3().crossVectors(right, direction).normalize();
    const tanV = Math.tan(verticalFov / 2);
    let distance = 1;
    for (const x of [bounds.min.x, bounds.max.x]) {
      for (const y of [bounds.min.y, bounds.max.y]) {
        for (const z of [bounds.min.z, bounds.max.z]) {
          const relative = new THREE.Vector3(x,y,z).sub(center);
          const depth = relative.dot(direction);
          distance = Math.max(distance, Math.abs(relative.dot(right)) / (tanV * camera.aspect) + depth,
            Math.abs(relative.dot(up)) / tanV + depth);
        }
      }
    }
    distance *= 1.12;
    camera.position.copy(center).addScaledVector(direction, distance);
    camera.near = Math.max(0.1, radius / 100);
    camera.far = Math.max(distance * 8, radius * 16, 2000);
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.minDistance = Math.max(radius * 0.12, 1);
    controls.maxDistance = Math.max(fullBounds?.getSize(new THREE.Vector3()).length() * 8 || radius * 20, distance * 3);
    controls.update();
    render();
  }

  function applyLayout() {
    const paired = sceneConfig.paired;
    const offset = modelId === 'camera' ? -66 : 66;
    primary.position.set(paired ? offset : 0,0,0);
    replica.group.position.set(paired ? -offset : 0,0,0);
    replica.setVisible(paired);
    desktop.setPairMode(paired);
    root.querySelector('label[for="robot-model-select"]').textContent = paired ? '查看版本' : '模型版本';
    root.querySelector('.rv-model-label').textContent = paired ? '摄像头版 × 屏幕版 · 同桌预览' : MODELS[modelId].title;
    root.querySelector('.rv-intro').textContent = paired ? '选择查看版本，再定位对应机器人的电机。' : '选择电机，透视查看它在装配体中的位置。';
    primary.updateMatrixWorld(true);
    replica.group.updateMatrixWorld(true);
  }

  function frameOverview() {
    viewMode = 'overview';
    root.dataset.view = viewMode;
    let bounds = fullBounds.clone().translate(primary.position);
    if (sceneConfig.paired && replica.bounds) bounds.union(replica.bounds.clone().translate(replica.group.position));
    const framing = sceneMode !== 'studio' ? (camera.aspect < 1 ? bounds.clone().expandByScalar(16) : desktop.getFramingBounds(bounds)) : bounds;
    frame(framing, true);
  }

  function updateMaterials() {
    const selected = new Set(selectedJoint?.meshes || []);
    meshes.forEach((mesh, index) => {
      const active = selected.has(index);
      const appearance = appearanceForPart(modelId, index, finishMode, active, xray);
      mesh.material.color.copy(appearance.color ? new THREE.Color(appearance.color) : mesh.userData.baseColor);
      mesh.material.emissive.set(appearance.emissive);
      for (const key of ['roughness','metalness','clearcoat','clearcoatRoughness','emissiveIntensity','transparent','opacity','depthWrite']) {
        mesh.material[key] = appearance[key];
      }
      mesh.castShadow = !xray;
      mesh.receiveShadow = !xray;
      mesh.material.needsUpdate = true;
      mesh.renderOrder = active ? 2 : 0;
    });
    if (eyeDisplay) eyeDisplay.visible = eyesEnabled && !xray;
    render();
  }

  function selectJoint(joint) {
    motionClock?.reset();
    selectedJoint = joint;
    xray = true;
    root.querySelector('.rv-xray').setAttribute('aria-pressed', 'true');
    jointAxes.visible = true;
    root.querySelector('.rv-axes').setAttribute('aria-pressed', 'true');
    root.querySelectorAll('.rv-joint').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.joint === joint?.id));
    });
    details.replaceChildren();
    addDetail(details, 'rv-detail-kicker', '无刷电机 · 结构定位', 'span');
    addDetail(details, '', joint.label, 'h3');
    addDetail(details, '', joint.description || '根据装配体外形定位的候选电机。请结合实物确认电机与转轴方向。', 'p');
    const selectedBounds = new THREE.Box3();
    (joint.meshes || []).forEach((index) => {
      if (meshes[index]) selectedBounds.expandByObject(meshes[index]);
    });
    updateMaterials();
    if (!selectedBounds.isEmpty()) {
      // Preserve surrounding mechanical context when inspecting a small motor.
      const minSize = fullBounds.getSize(new THREE.Vector3()).length() * 0.16;
      selectedBounds.expandByScalar(minSize);
      frame(selectedBounds);
    }
  }

  function overview() {
    selectedJoint = null;
    xray = false;
    jointAxes.visible = false;
    root.querySelector('.rv-xray').setAttribute('aria-pressed', 'false');
    root.querySelector('.rv-axes').setAttribute('aria-pressed', 'false');
    root.querySelectorAll('.rv-joint').forEach((button) => button.setAttribute('aria-pressed', 'false'));
    details.replaceChildren();
    addDetail(details, 'rv-detail-kicker', '装配体概览', 'span');
    addDetail(details, '', '真实结构，自由探索', 'h3');
    addDetail(details, '', `${meshes.length} 个 CAD 部件 · 尺寸单位：${manifest.units === 'mm' ? '毫米' : manifest.units || '模型单位'}。点击零件可查看名称，选择电机可聚焦对应位置。`, 'p');
    updateMaterials();
  }

  const sceneSelect = root.querySelector('.rv-scene-select');
  sceneSelect.value = sceneMode;
  function configureScene(updateUrl = true) {
    const resume = motionClock?.intent;
    motionClock?.reset();
    sceneMode = sceneSelect.value;
    sceneConfig = getSceneConfig(sceneMode);
    root.dataset.scene = sceneMode;
    root.dataset.theme = sceneConfig.theme;
    techDesktop.setVisible(false);
    warmDesktop.setVisible(false);
    desktop = sceneConfig.theme === 'warm' ? warmDesktop : techDesktop;
    const studio = sceneConfig.theme === 'studio';
    const tech = sceneConfig.theme === 'tech';
    desktop.setVisible(!studio);
    controls.maxPolarAngle = studio ? Math.PI : Math.PI / 2 - 0.04;
    floor.visible = studio;
    renderer.setClearColor(tech ? 0x252c31 : sceneConfig.theme === 'warm' ? 0xd7d0c5 : 0xece9e2);
    hemisphere.intensity = tech ? 0.4 : 0.65;
    keyLight.intensity = tech ? 1.9 : 3.2;
    keyLight.color.set(tech ? 0xdfeaff : 0xfff3de);
    fillLight.intensity = tech ? 0.65 : 1.1;
    scene.environmentIntensity = tech ? 0.48 : 0.65;
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('scene',sceneMode);
      window.history.replaceState(null,'',url);
    }
    if (fullBounds) { applyLayout(); overview(); frameOverview(); }
    else render();
    if (resume) motionClock.play();
  }
  sceneSelect.addEventListener('change', () => configureScene());
  configureScene(false);
  const finishSelect = root.querySelector('.rv-finish-select');
  finishSelect.addEventListener('change', () => {
    finishMode = finishSelect.value;
    root.dataset.finish = finishMode;
    updateMaterials();
    replica.setFinish(finishMode);
  });
  root.dataset.finish = finishMode;
  root.querySelector('.rv-eyes').addEventListener('click', (event) => {
    eyesEnabled = !eyesEnabled;
    replica.setEyesEnabled(eyesEnabled);
    event.currentTarget.setAttribute('aria-pressed', String(eyesEnabled));
    updateMaterials();
  });
  const motionToggle = root.querySelector('.rv-motion-toggle');
  const phaseLabel = root.querySelector('.rv-motion-phase');
  const timeline = root.querySelector('.rv-motion-timeline');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  function applyMotion(time) {
    if (root.dataset.modelStatus !== 'ready') return;
    const pose = sampleRobotMotion(time,modelId,sceneConfig.paired);
    primaryRig?.apply(pose);
    eyeDisplay?.userData.setMotionExpression?.(pose);
    replica.applyPose(sampleRobotMotion(time,modelId === 'camera' ? 'screen' : 'camera',sceneConfig.paired));
    root.dataset.motionTime = time.toFixed(2);
    root.dataset.motionYaw = pose.yaw.toFixed(5);
    root.dataset.motionPitch = pose.pitch.toFixed(5);
    root.dataset.motionBlink = pose.blink.toFixed(5);
    const localTime = time > 0 && time % MOTION_DURATION === 0 && !motionClock.intent ? MOTION_DURATION : time % MOTION_DURATION;
    timeline.value = String(Math.round(localTime*24));
    timeline.setAttribute('aria-valuetext',`${localTime.toFixed(2)}秒，${pose.phase}`);
    root.querySelector('.rv-motion-time').textContent = `${localTime.toFixed(2)} / ${MOTION_DURATION.toFixed(2)} s`;
    root.querySelector('.rv-motion-frame').textContent = `${Math.round(localTime*24)} / ${MOTION_DURATION*24} 帧`;
    if (phaseLabel.textContent !== pose.phase) phaseLabel.textContent = pose.phase;
    render();
  }
  motionClock = createMotionClock({onFrame:applyMotion,onState:({playing,intent,time}) => {
    root.dataset.motionState = playing ? 'playing' : intent ? 'suspended' : 'paused';
    motionToggle.textContent = intent ? '暂停互动' : '播放互动';
    motionToggle.setAttribute('aria-pressed',String(intent));
    if (!intent) phaseLabel.textContent = time === 0 ? '动作已归位' : `${sampleRobotMotion(time,modelId,sceneConfig.paired).phase} · 已暂停`;
  }});
  timeline.addEventListener('input',() => motionClock.seek(Number(timeline.value)/24));
  function stepFrame(delta) {
    const current = Number(timeline.value);
    motionClock.seek(Math.min(MOTION_DURATION*24,Math.max(0,current+delta))/24);
  }
  root.querySelector('.rv-motion-prev').addEventListener('click',() => stepFrame(-1));
  root.querySelector('.rv-motion-next').addEventListener('click',() => stepFrame(1));
  motionToggle.addEventListener('click', () => {
    if (motionClock.intent) motionClock.pause();
    else {overview();motionClock.play();}
  });
  root.querySelector('.rv-motion-reset').addEventListener('click',() => motionClock.reset());
  function frameInteraction() {
    viewMode = 'interaction';
    root.dataset.view = viewMode;
    const bounds=fullBounds.clone().translate(primary.position);
    if(sceneConfig.paired && replica.bounds)bounds.union(replica.bounds.clone().translate(replica.group.position));
    frame(bounds.expandByScalar(20),true);
  }
  root.querySelector('.rv-motion-focus').addEventListener('click',frameInteraction);
  document.addEventListener('visibilitychange',() => motionClock.setActive(root.dataset.modelStatus === 'ready' && !document.hidden));
  reducedMotion.addEventListener('change',() => {if(reducedMotion.matches)motionClock.pause();});
  window.addEventListener('pagehide',(event) => {
    if(event.persisted)motionClock.setActive(false);
    else motionClock.dispose();
  });
  window.addEventListener('pageshow',(event) => {
    if(event.persisted)motionClock.setActive(root.dataset.modelStatus === 'ready' && !document.hidden);
  });
  if (!reducedMotion.matches) motionClock.play();
  const loadLatestModel = createModelLoader();
  const loadOtherModel = createModelLoader();
  const modelSelect = root.querySelector('.rv-model-select');
  const requestedModel = new URLSearchParams(window.location.search).get('model');
  if (Object.hasOwn(MODELS, requestedModel)) modelSelect.value = requestedModel;

  function clearGroup(group) {
    group.traverse((object) => {
      object.geometry?.dispose();
      if (object.material) object.material.dispose();
    });
    group.clear();
  }

  async function loadModel(id) {
    const model = MODELS[id];
    loading.hidden = false;
    loading.classList.remove('rv-error');
    loading.setAttribute('role', 'status');
    loading.textContent = `正在载入${model.label}…`;
    root.dataset.modelStatus = 'loading';
    motionClock.setActive(false);
    root.querySelectorAll('.rv-reset, .rv-toggle, .rv-joint, .rv-motion-toggle, .rv-motion-reset, .rv-motion-focus, .rv-motion-timeline, .rv-motion-prev, .rv-motion-next').forEach((button) => { button.disabled = true; });
    try {
      const otherId = id === 'camera' ? 'screen' : 'camera';
      const [data, companionData] = await Promise.all([loadLatestModel(model),loadOtherModel(MODELS[otherId])]);
      if (!data || !companionData) return;
      ({manifest} = data);
      const {buffer} = data;
      if (!Array.isArray(manifest.meshes) || !manifest.bounds) throw new Error('模型清单格式不正确');
      fullBounds = boxFromBounds(manifest.bounds);
      if (fullBounds.isEmpty()) throw new Error('模型尺寸为空');
      eyeDisplay?.userData.stop?.();
      if (eyeDisplay) {
        eyeDisplay.removeFromParent();
        eyeDisplay.material.map.dispose();
        eyeDisplay.material.dispose();
        eyeDisplay.geometry.dispose();
        eyeDisplay = null;
      }
      modelId = id;
      clearGroup(assembly);
      clearGroup(jointAxes);
      selectedJoint = null;
      meshes = manifest.meshes.map((part, index) => {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(readArray(buffer, part.position, Float32Array), 3));
        if (part.normal?.count) geometry.setAttribute('normal', new THREE.BufferAttribute(readArray(buffer, part.normal, Float32Array), 3));
        geometry.setIndex(new THREE.BufferAttribute(readArray(buffer, part.index, Uint32Array), 1));
        if (!geometry.getAttribute('normal')) geometry.computeVertexNormals();
        geometry.computeBoundingSphere();
        const baseColor = cadColor(part.color);
        const material = new THREE.MeshPhysicalMaterial({ color: baseColor, roughness: 0.65, metalness: 0.18, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.name = part.name || `零件 ${index + 1}`;
        mesh.userData.baseColor = baseColor;
        assembly.add(mesh);
        return mesh;
      });
      primaryRig = createRobotRig(THREE,assembly,meshes,manifest);
      floor.position.z = fullBounds.min.z - 0.4;
      techDesktop.place(fullBounds);
      warmDesktop.place(fullBounds);
      replica.setModel(otherId,companionData,finishMode);
      const center = fullBounds.getCenter(new THREE.Vector3());
      keyLight.target.position.copy(center);
      keyLight.position.copy(center).add(new THREE.Vector3(-100,-150,240));
      if (id === 'screen') {
        eyeDisplay = createEyeDisplay(THREE, render, {animationDriven:true});
        primaryRig.attachHead(eyeDisplay);
      }
      root.querySelector('.rv-eyes').hidden = id !== 'screen';
      const size = fullBounds.getSize(new THREE.Vector3());
      const unit = manifest.units || '';
      root.querySelector('.rv-size').textContent = `${size.x.toFixed(0)} × ${size.y.toFixed(0)} × ${size.z.toFixed(0)} ${unit}`;
      const jointList = root.querySelector('.rv-joints');
      jointList.replaceChildren();
      (manifest.joints || []).forEach((joint, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'rv-joint';
        button.dataset.joint = joint.id;
        button.setAttribute('aria-pressed', 'false');
        addDetail(button, 'rv-joint-number', String(index + 1).padStart(2, '0'), 'span');
        const text = document.createElement('span');
        addDetail(text, 'rv-joint-title', joint.label || `候选电机 ${index + 1}`, 'strong');
        addDetail(text, 'rv-joint-subtitle', '定位电机与转轴', 'small');
        button.append(text);
        addDetail(button, 'rv-joint-arrow', '↗', 'span');
        button.addEventListener('click', () => selectJoint(joint));
        jointList.append(button);
        if (joint.origin?.length === 3 && joint.axis?.length === 3) {
          const direction = new THREE.Vector3(...joint.axis);
          if (direction.lengthSq() > 0) {
            const length = Math.max(size.length() * 0.23, 1);
            const origin = new THREE.Vector3(...joint.origin);
            const arrow = new THREE.ArrowHelper(direction.normalize(), origin, length, index ? 0xd38a35 : 0x189080, length * 0.13, length * 0.065);
            arrow.traverse((object) => {
              if (object.material) {
                object.material.depthTest = false;
                object.material.transparent = true;
                object.material.opacity = 0.9;
                object.renderOrder = 5;
              }
            });
            jointAxes.add(arrow);
          }
        }
      });
      root.querySelector('.rv-model-label').replaceChildren();
      addDetail(root.querySelector('.rv-model-label'), '', '', 'i');
      root.querySelector('.rv-model-label').append(document.createTextNode(model.title));
      root.querySelectorAll('.rv-reset, .rv-toggle, .rv-motion-toggle, .rv-motion-reset, .rv-motion-focus, .rv-motion-timeline, .rv-motion-prev, .rv-motion-next').forEach((button) => { button.disabled = false; });
      loading.hidden = true;
      root.dataset.modelId = id;
      root.dataset.modelStatus = 'ready';
      applyLayout();
      overview();
      frameOverview();
      applyMotion(motionClock.time);
      motionClock.setActive(!document.hidden);
    } catch (error) {
      root.dataset.modelStatus = 'error';
      showError(loading, `模型暂时无法显示：${error.message}。可重新选择版本重试。`);
    }
  }

  modelSelect.addEventListener('change', () => {
    const url = new URL(window.location.href);
    url.searchParams.set('model', modelSelect.value);
    window.history.replaceState(null, '', url);
    loadModel(modelSelect.value);
  });
  root.querySelector('.rv-reset').addEventListener('click', () => { motionClock.reset();overview(); frameOverview(); });
  root.querySelector('.rv-xray').addEventListener('click', (event) => {
    motionClock.reset();
    xray = !xray;
    event.currentTarget.setAttribute('aria-pressed', String(xray));
    updateMaterials();
  });
  root.querySelector('.rv-axes').addEventListener('click', (event) => {
    motionClock.reset();
    jointAxes.visible = !jointAxes.visible;
    event.currentTarget.setAttribute('aria-pressed', String(jointAxes.visible));
    render();
  });
  await loadModel(modelSelect.value);

  const raycaster = new THREE.Raycaster();
  let pointerStart = null;
  renderer.domElement.addEventListener('pointerdown', (event) => { pointerStart = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (root.dataset.modelStatus !== 'ready' || !pointerStart || Math.hypot(event.clientX - pointerStart[0], event.clientY - pointerStart[1]) > 5) return;
    pointerStart = null;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(meshes, false);
    if (!hits.length) return;
    const hit = xray && selectedJoint
      ? hits.find(({ object }) => selectedJoint.meshes.includes(meshes.indexOf(object))) || hits[0]
      : hits[0];
    const partName = hit.object.name;
    details.replaceChildren();
    addDetail(details, 'rv-detail-kicker', '已选 CAD 零件', 'span');
    addDetail(details, '', partName, 'h3');
    addDetail(details, '', '名称来自 STEP 装配体。选择上方电机可查看关联结构。', 'p');
  });
}

function addDetail(parent, className, text, tag) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function showError(element, text) {
  element.hidden = false;
  element.classList.add('rv-error');
  element.setAttribute('role', 'alert');
  element.textContent = text;
}

function boxFromBounds(bounds) {
  if (!Array.isArray(bounds.min) || !Array.isArray(bounds.max) || [...bounds.min, ...bounds.max].some((value) => !Number.isFinite(value))) {
    throw new Error('模型边界数据无效');
  }
  return new THREE.Box3(new THREE.Vector3(...bounds.min), new THREE.Vector3(...bounds.max));
}

function readArray(buffer, range, ArrayType) {
  if (!range || !Number.isInteger(range.offset) || !Number.isInteger(range.count) || range.offset < 0 || range.count < 0 || range.offset % ArrayType.BYTES_PER_ELEMENT || range.offset + range.count * ArrayType.BYTES_PER_ELEMENT > buffer.byteLength) {
    throw new Error('模型几何数据不完整');
  }
  return new ArrayType(buffer, range.offset, range.count);
}

function cadColor(value) {
  if (Array.isArray(value) && value.length >= 3) {
    const scale = Math.max(...value.slice(0, 3)) > 1 ? 255 : 1;
    return new THREE.Color(value[0] / scale, value[1] / scale, value[2] / scale);
  }
  return new THREE.Color(value || '#b7c5ca');
}

const root = document.getElementById('robot-viewer');
if (root) mountRobotViewer(root);
