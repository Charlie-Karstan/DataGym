'use strict';

const fs = require('node:fs');
const { once } = require('node:events');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { setTimeout: delay } = require('node:timers/promises');

async function main() {
  const vsix = process.argv[2];
  if (!vsix) throw new Error('Usage: node tests/vscode/run.js path/to/datagym.vsix');

  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'datagym-acceptance-'));
  console.log('Isolated VS Code profile and test logs:', root);
  const userData = path.join(root, 'user');
  const user = path.join(userData, 'User');
  const extensions = path.join(root, 'extensions');
  const profileName = 'DataGym Standalone Test';
  const profileId = 'datagym-standalone-test';
  const profile = path.join(user, 'profiles', profileId);
  const modern = process.env.DATAGYM_TEST_PYTHON_ENVS !== '0';
  const requireTrust = process.env.DATAGYM_TEST_REQUIRE_TRUST === '1';
  const restrictedReopen = process.env.DATAGYM_TEST_RESTRICTED_REOPEN === '1';
  const args = ['--user-data-dir', userData, '--extensions-dir', extensions];
  const cli = process.env.DATAGYM_VSCODE_CLI || 'code';
  const executable = process.env.DATAGYM_VSCODE_EXECUTABLE || (process.platform === 'darwin'
    ? '/Applications/Visual Studio Code.app/Contents/MacOS/Code' : cli);
  const dependencies = ['ms-python.python', 'ms-python.vscode-pylance', 'ms-python.debugpy'];
  if (modern) dependencies.push('ms-python.vscode-python-envs');
  fs.mkdirSync(profile, { recursive: true });
  fs.mkdirSync(extensions);
  fs.writeFileSync(path.join(profile, 'settings.json'), JSON.stringify({
    'workbench.enableExperiments': false,
    'python.experiments.enabled': false,
    'python.useEnvironmentsExtension': modern,
    'python.analysis.logLevel': 'Trace',
    'telemetry.telemetryLevel': 'off',
    'update.mode': 'none',
    'extensions.autoUpdate': 'off',
  }));
  if (requireTrust || restrictedReopen) {
    const workspace = path.join(userData, 'User', 'globalStorage', 'charliekarstan.datagym-vscode', 'workspace');
    fs.mkdirSync(workspace, { recursive: true });
    fs.writeFileSync(path.join(workspace, 'solution.py'), 'import numpy as np\nresult = np.\n');
  }

  function install(extension) {
    const result = spawnSync(cli, [...args, '--install-extension', extension, '--force'],
      { stdio: 'inherit', shell: process.platform === 'win32', timeout: 120000 });
    if (result.status !== 0) throw result.error || new Error(`Could not install ${extension}`);
  }

  const cache = process.env.DATAGYM_TEST_EXTENSION_CACHE;
  if (cache) {
    for (const entry of fs.readdirSync(cache)) {
      if (!dependencies.some(id => entry.startsWith(id + '-'))) continue;
      fs.cpSync(path.join(cache, entry), path.join(extensions, entry), { recursive: true });
    }
  } else {
    for (const dependency of dependencies) install(dependency);
  }
  // A separate test extension runs in both hosts across vscode.openFolder.
  const driver = path.join(extensions, 'datagym-test.acceptance');
  fs.mkdirSync(driver);
  fs.copyFileSync(path.join(__dirname, 'acceptance.js'), path.join(driver, 'extension.js'));
  fs.writeFileSync(path.join(driver, 'package.json'), JSON.stringify({
    name: 'acceptance', publisher: 'datagym-test', version: '0.0.1',
    engines: { vscode: '^1.90.0' }, main: './extension.js', activationEvents: ['onStartupFinished'],
    capabilities: { untrustedWorkspaces: { supported: true } },
  }));
  install(path.resolve(vsix));
  // Point a named profile in this disposable VS Code instance at the installed test extensions.
  fs.copyFileSync(path.join(extensions, 'extensions.json'), path.join(profile, 'extensions.json'));
  const globalStorage = path.join(user, 'globalStorage');
  fs.mkdirSync(globalStorage, { recursive: true });
  const storageFile = path.join(globalStorage, 'storage.json');
  const storage = fs.existsSync(storageFile) ? JSON.parse(fs.readFileSync(storageFile, 'utf8')) : {};
  storage.userDataProfiles = [{ location: profileId, name: profileName }];
  fs.writeFileSync(storageFile, JSON.stringify(storage));
  const env = { ...process.env, DATAGYM_ACCEPTANCE_ROOT: root };
  delete env.ELECTRON_RUN_AS_NODE;
  const launchArgs = [...args, '--new-window', '--profile', profileName, '--skip-release-notes'];
  if (requireTrust) console.log('Grant Workspace Trust to the disposable DataGym workspace when it opens.');
  let app;
  let launchError;
  function launch(extraArgs, logName) {
    const log = fs.openSync(path.join(root, logName), 'w');
    app = spawn(executable, [...launchArgs, ...extraArgs], { env, stdio: ['ignore', log, log] });
    fs.closeSync(log);
    app.on('error', error => { launchError = error; });
  }

  launch(requireTrust || restrictedReopen ? [] : ['--disable-workspace-trust'], 'application.log');
  try {
    const report = path.join(root, 'result.json');
    const restricted = path.join(root, 'restricted.json');
    let reopened = false;
    const timeout = Date.now() + (requireTrust ? 240000 : 150000);
    while (Date.now() < timeout) {
      if (fs.existsSync(report)) {
        const result = JSON.parse(fs.readFileSync(report, 'utf8'));
        console.log(JSON.stringify(result, null, 2));
        if (!result.ok) throw new Error('VS Code acceptance failed.');
        return;
      }
      if (launchError) throw launchError;
      if (app.exitCode !== null) throw new Error(`VS Code closed before the test finished (${app.exitCode}).`);
      if (restrictedReopen && !reopened && fs.existsSync(restricted)) {
        const { workspace } = JSON.parse(fs.readFileSync(restricted, 'utf8'));
        const stopping = once(app, 'exit');
        app.kill();
        await stopping;
        launch(['--disable-workspace-trust', workspace], 'trusted-application.log');
        reopened = true;
      }
      await delay(500);
    }
    throw new Error('Timed out waiting for the standalone VS Code test.');
  } finally {
    app.kill();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
