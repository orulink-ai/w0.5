/** Canvas texture aligned to the screen's measured CAD front plane. */
export function createEyeDisplay(THREE, render, {animationDriven = false} = {}) {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.MeshBasicMaterial({map:texture, toneMapped:false});
  const display = new THREE.Mesh(new THREE.PlaneGeometry(30.2, 14.6), material);
  const normal = new THREE.Vector3(0, -0.93969262, 0.34202014);
  display.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), normal);
  display.position.set(33.35953258, 15.20264186, 81.46674742).addScaledVector(normal, 0.08);
  display.name = '屏幕表情预览';
  display.renderOrder = 1;
  let timeout;
  let stopped = false;
  let motionOpenness = 1;
  let gazeX = 0;
  let gazeY = 0;
  let autoOpenness = 1;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function draw(openness = autoOpenness) {
    autoOpenness = openness;
    openness = Math.min(autoOpenness, motionOpenness);
    ctx.fillStyle = '#061115';
    ctx.fillRect(0,0,1024,512);
    const glow = ctx.createRadialGradient(512,250,20,512,250,500);
    glow.addColorStop(0,'#103239');
    glow.addColorStop(1,'#061115');
    ctx.fillStyle = glow;
    ctx.fillRect(0,0,1024,512);
    for (const originX of [210, 610]) {
      const x = originX + gazeX * 60;
      const height = Math.max(18, 220 * openness);
      const y = 245 - height / 2 + gazeY * 38;
      const gradient = ctx.createLinearGradient(0,y,0,y+height);
      gradient.addColorStop(0,'#b5ffef');
      gradient.addColorStop(0.45,'#4fe6da');
      gradient.addColorStop(1,'#1b94b7');
      ctx.fillStyle = gradient;
      ctx.shadowColor = '#42decf';
      ctx.shadowBlur = 25;
      ctx.beginPath();
      ctx.roundRect(x,y,204,height,Math.min(65,height/2));
      ctx.fill();
      ctx.shadowBlur = 0;
      if (openness > 0.5) {
        ctx.fillStyle = '#e7fffa';
        ctx.globalAlpha = 0.45;
        ctx.beginPath();ctx.ellipse(x+58,y+47,17,10,-0.5,0,Math.PI*2);ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
    ctx.strokeStyle = '#46b8b6';
    ctx.lineWidth = 8;
    ctx.lineCap = 'round';
    ctx.beginPath();ctx.moveTo(484,367);ctx.quadraticCurveTo(512,392,540,367);ctx.stroke();
    texture.needsUpdate = true;
    render();
  }

  function schedule() {
    if (stopped || reducedMotion.matches) return;
    timeout = setTimeout(() => {
      if (!display.visible || document.hidden) { schedule(); return; }
      draw(0.06);
      timeout = setTimeout(() => {
        if (stopped) return;
        draw(1);
        schedule();
      }, 140);
    }, 3200 + Math.random()*1800);
  }
  display.userData.setMotionOpenness = (value) => {
    const openness = Number.isFinite(value) ? Math.min(1,Math.max(0,value)) : 1;
    if (Math.abs(openness-motionOpenness)<1e-6) return;
    motionOpenness = openness;
    draw();
  };
  display.userData.setMotionExpression = ({blink=1,gazeX:nextX=0,gazeY:nextY=0}) => {
    const clamp = (value,min,max,fallback) => Number.isFinite(value) ? Math.min(max,Math.max(min,value)) : fallback;
    const next = [clamp(blink,0,1,1),clamp(nextX,-1,1,0),clamp(nextY,-1,1,0)];
    if(next.every((value,index)=>Math.abs(value-[motionOpenness,gazeX,gazeY][index])<1e-6))return;
    [motionOpenness,gazeX,gazeY]=next;
    draw();
  };
  display.userData.stop = () => {stopped=true; clearTimeout(timeout);};
  draw();
  if (!animationDriven) schedule();
  return display;
}
