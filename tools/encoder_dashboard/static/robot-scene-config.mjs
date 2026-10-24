export const SCENE_CONFIGS = Object.freeze({
  pair: {theme:'tech', paired:true},
  desk: {theme:'tech', paired:false},
  'warm-pair': {theme:'warm', paired:true},
  'warm-desk': {theme:'warm', paired:false},
  studio: {theme:'studio', paired:false},
});
export function getSceneConfig(mode) {
  return SCENE_CONFIGS[mode] || SCENE_CONFIGS.pair;
}
