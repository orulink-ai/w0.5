const path = require('node:path');
const {convert} = require('./convert-step.cjs');

async function convertAll() {
  const destination = path.join(__dirname, '../encoder_dashboard/static/models');
  await convert(path.join(__dirname, '../../hardware/models/robot-camera.step'), destination,
    path.join(__dirname, 'robot-joints.json'), 'robot');
  await convert(path.join(__dirname, '../../hardware/models/robot-screen.step'), destination,
    path.join(__dirname, 'robot-screen-joints.json'), 'robot-screen');
}
convertAll().catch(error => {console.error(error.message); process.exitCode = 1;});
