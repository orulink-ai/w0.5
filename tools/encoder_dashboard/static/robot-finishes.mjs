const FINISHES = {
  shell: {color:'#e8e4da', roughness:0.42, metalness:0, clearcoat:0.22, clearcoatRoughness:0.36},
  frame: {color:'#303b3d', roughness:0.46, metalness:0.65},
  motor: {color:'#647072', roughness:0.29, metalness:0.88},
  electronics: {color:'#253b34', roughness:0.65, metalness:0.12},
  lining: {color:'#253133', roughness:0.62, metalness:0.1},
  accent: {color:'#cf7950', roughness:0.38, metalness:0.2},
  bezel: {color:'#121e24', roughness:0.24, metalness:0.55},
  lens: {color:'#113744', roughness:0.09, metalness:0.3, clearcoat:1, emissive:'#123a48', emissiveIntensity:0.16},
  display: {color:'#07171b', roughness:0.13, metalness:0.15, clearcoat:1, emissive:'#092e35', emissiveIntensity:0.12},
};
const COMMON = ['electronics','frame','motor','frame','shell','frame','shell','motor','frame','frame'];
const ROLES = {
  camera: [...COMMON,'bezel','bezel','lens','shell','lining','accent','accent'],
  screen: [...COMMON,'display','shell'],
};
export function finishForPart(model, index) {
  const role = ROLES[model]?.[index] || 'frame';
  return {role, ...FINISHES[role]};
}
export function appearanceForPart(model, index, mode, active, xray) {
  const finish = mode === 'cad' ? {color:null, roughness:0.65, metalness:0.18} : finishForPart(model,index);
  return {
    color:active ? '#e88b35' : finish.color,
    roughness:finish.roughness, metalness:finish.metalness,
    clearcoat:finish.clearcoat || 0, clearcoatRoughness:finish.clearcoatRoughness || 0.2,
    emissive:active ? '#e88b35' : finish.emissive || '#000000',
    emissiveIntensity:active ? 0.32 : finish.emissiveIntensity || 0,
    transparent:xray && !active, opacity:xray && !active ? 0.15 : 1,
    depthWrite:!(xray && !active),
  };
}
