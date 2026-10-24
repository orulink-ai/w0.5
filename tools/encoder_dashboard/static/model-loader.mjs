/** Fetch a manifest/buffer pair; a late previous selection never becomes active. */
export function createModelLoader(fetcher = fetch) {
  let generation = 0;
  let controller;
  return async function loadModel(model) {
    const request = ++generation;
    controller?.abort();
    controller = new AbortController();
    const options = {signal: controller.signal};
    try {
      const responses = await Promise.all([fetcher(model.manifest, options), fetcher(model.binary, options)]);
      if (responses.some(response => !response.ok)) throw new Error('模型资源尚未就绪');
      const [manifest, buffer] = await Promise.all([responses[0].json(), responses[1].arrayBuffer()]);
      return request === generation ? {manifest, buffer} : null;
    } catch (error) {
      if (request !== generation) return null;
      throw error;
    }
  };
}
