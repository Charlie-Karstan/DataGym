'use strict';

const fs = require('fs');
const path = require('path');

const project = path.resolve(__dirname, '../..');
const runtime = path.join(project, 'extension', 'runtime');
const include = ['app.py', 'requirements.txt', 'datagym', 'exercise_packs', 'static'];

fs.rmSync(runtime, { recursive: true, force: true });
fs.mkdirSync(runtime, { recursive: true });

for (const name of include) {
  fs.cpSync(path.join(project, name), path.join(runtime, name), {
    recursive: true,
    filter: item => !item.split(path.sep).includes('__pycache__') && !item.endsWith('.pyc'),
  });
}

console.log('DataGym runtime staged:', include.join(', '));
