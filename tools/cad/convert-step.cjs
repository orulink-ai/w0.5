#!/usr/bin/env node
/* CAD coordinates remain millimetres, Z up. The browser never parses STEP. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function convert(source, destination, jointFile, stem = "robot") {
  const content = fs.readFileSync(source);
  const occt = await require('occt-import-js')();
  const result = occt.ReadStepFile(content, {
    linearUnit: 'millimeter', linearDeflectionType: 'absolute_value',
    linearDeflection: 0.12, angularDeflection: 0.25,
  });
  if (!result.success || !result.meshes.length) throw new Error('STEP conversion failed');
  const names = new Map();
  function visit(node) {
    node.meshes.forEach(index => names.set(index, node.name));
    node.children.forEach(visit);
  }
  visit(result.root);
  const chunks = [];
  let offset = 0;
  function pack(values, type) {
    const bytes = Buffer.alloc(values.length * 4);
    values.forEach((value, i) => {
      if (!Number.isFinite(value)) throw new Error('Non-finite geometry');
      if (type === 'index') bytes.writeUInt32LE(value, i * 4);
      else bytes.writeFloatLE(value, i * 4);
    });
    const accessor = {offset, count: values.length};
    chunks.push(bytes);
    offset += bytes.length;
    return accessor;
  }
  const bounds = {min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity]};
  const meshes = result.meshes.map((mesh, i) => {
    const positions = mesh.attributes.position.array;
    const box = {min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity]};
    positions.forEach((value, j) => {
      const axis = j % 3;
      box.min[axis] = Math.min(box.min[axis], value);
      box.max[axis] = Math.max(box.max[axis], value);
      bounds.min[axis] = Math.min(bounds.min[axis], value);
      bounds.max[axis] = Math.max(bounds.max[axis], value);
    });
    return {
      name: (mesh.name || names.get(i) || `零件 ${i + 1}`).replace(/[\r\n]/g, ''),
      color: mesh.color || [0.65, 0.69, 0.72], bounds: box,
      position: pack(positions), normal: pack(mesh.attributes.normal.array),
      index: pack(mesh.index.array, 'index'),
    };
  });
  // The CAD has shapes but no kinematic constraints. These motor axes are
  // geometric candidates, not a firmware zero, direction or travel limit.
  const joints = JSON.parse(fs.readFileSync(jointFile || path.join(__dirname, 'robot-joints.json')));
  const model = {formatVersion: 1, units: 'mm', source: path.basename(source),
    sourceSha256: crypto.createHash('sha256').update(content).digest('hex'),
    tessellation: {linearDeflection: 0.12, angularDeflection: 0.25},
    bounds, meshes, joints};
  fs.mkdirSync(destination, {recursive: true});
  fs.writeFileSync(path.join(destination, `${stem}.bin`), Buffer.concat(chunks));
  fs.writeFileSync(path.join(destination, `${stem}.json`), JSON.stringify(model, null, 2) + '\n');
  console.log(`Converted ${meshes.length} meshes, ${offset} bytes`);
}
if (require.main === module) {
  convert(process.argv[2] || path.join(__dirname, '../../hardware/models/robot-camera.step'),
    process.argv[3] || path.join(__dirname, '../encoder_dashboard/static/models'), process.argv[4], process.argv[5])
    .catch(error => {console.error(error.message); process.exitCode = 1;});
}
module.exports = {convert};
