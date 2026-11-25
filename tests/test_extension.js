'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'extension', 'extension.js'), 'utf8');
const manifest = require('../extension/package.json');
const requirements = 'pandas>=2.2,<4\nnumpy>=2.0,<3\n';
const fingerprint = crypto.createHash('sha256').update(requirements).digest('hex');

class TabInputText {
  constructor(fsPath) { this.uri = { toString: () => fsPath }; }
}

function fixture(t) {
  const storage = fs.mkdtempSync(path.join(os.tmpdir(), 'datagym-test-'));
  t.after(() => fs.rmSync(storage, { recursive: true, force: true }));
  const folder = path.join(storage, 'workspace');
  return {
    storage, folder,
    workspace: path.join(folder, 'DataGym.code-workspace'),
    solution: path.join(folder, 'solution.py'),
    python: path.join(storage, 'venv', ...(process.platform === 'win32'
      ? ['Scripts', 'python.exe'] : ['bin', 'python'])),
  };
}

function loadExtension(files, {
  managed = false,
  workspaceFile = managed ? files.workspace : undefined,
  folders = managed ? [files.folder] : [],
  tabs = [],
  editor,
  version = 'current',
  activePython,
  modernPython,
  usePythonEnvs = false,
  pythonReady,
  trusted = true,
  extraPaths,
  pythonAvailable = true,
  selectEnvironment,
  useDownloadAction = false,
} = {}) {
  const commands = new Map();
  const calls = { opens: [], layouts: [], processes: [], configuration: [], interpreters: [], modern: [], closedTabs: [],
    errors: [], warnings: [], urls: [], panels: 0, documentOpens: 0 };
  const uri = fsPath => ({ fsPath, toString: () => fsPath });
  const extensionPath = path.join(files.storage, version);
  const runtime = path.join(extensionPath, 'runtime');
  fs.mkdirSync(path.join(runtime, 'static'), { recursive: true });
  fs.writeFileSync(path.join(runtime, 'requirements.txt'), requirements);
  fs.writeFileSync(path.join(runtime, 'static', 'index.html'), '<html><head></head><body></body></html>');
  const document = editor?.document ?? {
    uri: uri(files.solution),
    languageId: 'python',
    lineCount: 1,
    lineAt: () => ({ text: 'result = ' }),
  };
  let windowStateChanged;
  let grantTrust;
  let fileChanged;
  let disposePanel;
  const mockPanel = {
    reveal() {},
    webview: { asWebviewUri: value => value, onDidReceiveMessage() {}, postMessage() {} },
    onDidDispose(handler) { disposePanel = handler; },
  };

  const vscode = {
    workspace: {
      workspaceFile: workspaceFile && uri(workspaceFile),
      workspaceFolders: folders.map(folder => ({ uri: uri(folder) })),
      get isTrusted() { return trusted; },
      onDidGrantWorkspaceTrust(handler) {
        grantTrust = handler;
        return { dispose() {} };
      },
      onDidChangeTextDocument: () => ({ dispose() {} }),
      getConfiguration(section, resource) {
        if (section === 'datagym') return { get: () => '' };
        return {
          inspect(key) {
            if (key === 'analysis.extraPaths') return { workspaceValue: extraPaths };
            if (key === 'useEnvironmentsExtension') return { globalValue: usePythonEnvs };
          },
          async update(key, value, target) {
            calls.configuration.push({ section, resource: resource.fsPath, key,
              value: Array.isArray(value) ? [...value] : value, target });
            if (key === 'analysis.extraPaths') extraPaths = value;
          },
        };
      },
      openTextDocument: async () => {
        calls.documentOpens += 1;
        return document;
      },
    },
    window: {
      visibleTextEditors: editor ? [editor] : [],
      tabGroups: {
        all: [{ tabs }],
        async close(closed) {
          calls.closedTabs.push(...closed);
          for (const tab of closed) tabs.splice(tabs.indexOf(tab), 1);
          return true;
        },
      },
      onDidChangeWindowState(handler) {
        windowStateChanged = handler;
        return { dispose() {} };
      },
      createOutputChannel: () => ({ append() {}, appendLine() {}, show() {}, dispose() {} }),
      withProgress: (_options, task) => task(),
      createWebviewPanel() {
        calls.panels += 1;
        return mockPanel;
      },
      showTextDocument: async doc => ({ document: doc, revealRange() {} }),
      showErrorMessage: async (message, action) => {
        calls.errors.push({ message, action });
        return useDownloadAction ? action : undefined;
      },
      showWarningMessage: message => calls.warnings.push(message),
    },
    commands: {
      registerCommand: (name, handler) => {
        commands.set(name, handler);
        return { dispose() {} };
      },
      async executeCommand(name, ...args) {
        if (name === 'vscode.openFolder') {
          calls.opens.push([args[0].fsPath, { ...args[1] }]);
        } else if (name === 'vscode.setEditorLayout') {
          calls.layouts.push(args[0]);
        } else {
          throw new Error(`Unexpected command ${name}`);
        }
      },
    },
    extensions: {
      getExtension(id) {
        if (id === 'ms-python.vscode-python-envs' && usePythonEnvs) {
          const environment = executable => ({ execInfo: { run: { executable } } });
          return { activate: async () => ({
            async getEnvironment(resource) {
              assert.equal(resource.fsPath, files.solution);
              return environment(modernPython);
            },
            async resolveEnvironment(resource) {
              return environment(resource.fsPath);
            },
            async setEnvironment(resource, selected) {
              calls.modern.push([selected.execInfo.run.executable, resource.fsPath]);
              modernPython = selected.execInfo.run.executable;
            },
          }) };
        }
        assert.equal(id, 'ms-python.python');
        return {
          activate: async () => ({
            ready: pythonReady,
            environments: {
              getActiveEnvironmentPath(resource) {
                assert.equal(resource.fsPath, files.solution);
                return { path: activePython };
              },
              async updateActiveEnvironmentPath(python, resource) {
                calls.interpreters.push([python, resource.fsPath]);
                await selectEnvironment?.();
                activePython = python;
              },
            },
          }),
        };
      },
    },
    languages: {
      async setTextDocumentLanguage(doc, languageId) {
        return Object.assign(doc, { languageId });
      },
    },
    env: { openExternal: async url => calls.urls.push(url.toString()) },
    Uri: { file: uri, joinPath: (base, name) => uri(path.join(base.fsPath, name)), parse: uri },
    ConfigurationTarget: { Workspace: 2 },
    TabInputText,
    ProgressLocation: { Notification: 15 },
    ViewColumn: { One: 1, Two: 2 },
    Position: class { constructor(line, character) { Object.assign(this, { line, character }); } },
    Selection: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
  };

  const childProcess = {
    spawnSync: () => ({ status: pythonAvailable ? 0 : 1 }),
    spawn(command, args, options) {
      calls.processes.push({ command, args: [...args], options });
      const child = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter() });
      queueMicrotask(() => {
        if (args[0] === 'app.py') {
          child.stdout.emit('data', 'DATAGYM_READY 8765');
        } else {
          if (args.includes('venv')) {
            fs.mkdirSync(path.dirname(files.python), { recursive: true });
            fs.writeFileSync(files.python, '');
          }
          child.emit('close', 0);
        }
      });
      return child;
    },
  };
  const context = {
    require: name => {
      if (name === 'vscode') return vscode;
      if (name === 'child_process') return childProcess;
      if (name === 'fs') return { ...fs, watch: (_path, _options, handler) => {
        fileChanged = handler;
        return { on() {}, close() {} };
      } };
      return require(name);
    },
    module: { exports: {} },
    process,
    setTimeout,
    clearTimeout,
    AbortSignal,
    AbortController,
    fetch: async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) }),
  };
  vm.runInNewContext(source, context, { filename: 'extension.js' });
  context.module.exports.activate({
    subscriptions: [],
    extensionPath,
    globalStorageUri: uri(files.storage),
  });
  return {
    calls, commands, runtime,
    open: commands.get('datagym.open'),
    focus: () => windowStateChanged({ focused: true }),
    fileChanged: () => fileChanged('rename', 'open-trainer'),
    trust: () => { trusted = true; grantTrust(); },
    closePanel: () => disposePanel(),
  };
}

test('declares Python and Pylance dependencies and activates inside the trainer workspace', () => {
  assert.deepEqual(manifest.extensionDependencies, ['ms-python.python', 'ms-python.vscode-pylance']);
  assert.ok(manifest.activationEvents.includes('workspaceContains:DataGym.code-workspace'));
});

test('fresh launch hands off to a managed workspace in the empty window', async t => {
  const files = fixture(t);
  const from = loadExtension(files, { tabs: [{ label: 'Welcome' }] });
  await Promise.all([from.open(), from.open()]);

  assert.deepEqual(from.calls.opens, [[files.workspace, { forceReuseWindow: true, forceNewWindow: false }]]);
  assert.deepEqual(JSON.parse(fs.readFileSync(files.workspace, 'utf8')), {
    folders: [{ path: '.' }],
    settings: { 'python.analysis.extraPaths': [from.runtime] },
  });
  assert.deepEqual(from.calls.processes, []);
  assert.deepEqual(from.calls.configuration, []);
  assert.deepEqual(from.calls.interpreters, []);

  const trainer = loadExtension(files, { managed: true });
  await Promise.all([trainer.open(), trainer.open()]);

  assert.deepEqual(trainer.calls.opens, []);
  assert.deepEqual(trainer.calls.processes.map(({ args }) => args[1] ?? args[0]), ['venv', 'pip', 'app.py']);
  const backend = trainer.calls.processes.at(-1);
  assert.equal(backend.command, files.python);
  assert.equal(backend.options.env.DATAGYM_WORKSPACE, files.folder);
  assert.deepEqual(trainer.calls.interpreters, [[files.python, files.folder]]);
  assert.deepEqual(trainer.calls.configuration, [
    { section: 'python', resource: files.solution, key: 'analysis.extraPaths', value: [trainer.runtime], target: 2 },
  ]);
  assert.equal(trainer.calls.panels, 1);
  const [layout] = trainer.calls.layouts;
  assert.equal(layout.orientation, 1);
  assert.deepEqual(Array.from(layout.groups, group => group.size), [0.8, 0.2]);
  assert.equal(fs.readFileSync(path.join(files.storage, 'dependencies.sha256'), 'utf8'), fingerprint);
});

test('opens a separate window from unrelated folders, workspaces and file-only windows', async t => {
  const files = fixture(t);
  for (const window of [
    { folders: [path.join(files.storage, 'other-project')] },
    { workspaceFile: path.join(files.storage, 'other-project', 'DataGym.code-workspace'), folders: [files.folder] },
    { workspaceFile: files.workspace, folders: [files.folder, path.join(files.storage, 'other-project')] },
    { tabs: [{ input: new TabInputText(path.join(files.storage, 'unrelated.py')) }] },
    { tabs: [{ isDirty: true }] },
  ]) {
    const from = loadExtension(files, window);
    await from.commands.get('datagym.next')();
    await from.open();
    assert.deepEqual(from.calls.opens, [[files.workspace, { forceReuseWindow: false, forceNewWindow: true }]]);
    assert.deepEqual(from.calls.processes, []);
    assert.deepEqual(from.calls.configuration, []);
    assert.deepEqual(from.calls.interpreters, []);
  }
});

test('an open DataGym window handles a launch request without a focus change', async t => {
  const files = fixture(t);
  const trainer = loadExtension(files, { managed: true });
  await trainer.open();
  trainer.closePanel();
  trainer.focus();
  assert.equal(trainer.calls.panels, 1);

  const from = loadExtension(files);
  await from.open();
  trainer.fileChanged();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(trainer.calls.panels, 2);
  assert.equal(trainer.calls.processes.filter(({ args }) => args[0] === 'app.py').length, 1);
  assert.equal(fs.existsSync(path.join(files.storage, 'open-trainer')), false);
});

test('a pending handoff survives Restricted Mode and waits for Python initialization', async t => {
  const files = fixture(t);
  let finishPython;
  const pythonReady = new Promise(resolve => { finishPython = resolve; });
  const from = loadExtension(files);
  await from.open();
  const trainer = loadExtension(files, {
    managed: true, trusted: false, usePythonEnvs: true,
    activePython: files.python, modernPython: path.join(files.storage, 'system', 'python'), pythonReady,
  });
  const request = path.join(files.storage, 'open-trainer');
  await trainer.open();
  assert.equal(fs.existsSync(request), true);
  assert.equal(trainer.calls.panels, 0);
  trainer.trust();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(trainer.calls.panels, 1);
  assert.equal(trainer.calls.documentOpens, 0);
  assert.deepEqual(trainer.calls.modern, []);
  assert.equal(fs.existsSync(request), true);
  finishPython();
  await trainer.open();
  assert.deepEqual(trainer.calls.modern, [[files.python, files.folder]]);
  assert.deepEqual(trainer.calls.interpreters, []);
  assert.equal(trainer.calls.documentOpens, 1);
  assert.equal(fs.existsSync(request), false);
});

test('an upgrade refreshes the runtime path and reuses the existing interpreter and user data', async t => {
  const files = fixture(t);
  fs.mkdirSync(path.dirname(files.python), { recursive: true });
  fs.mkdirSync(files.folder);
  fs.writeFileSync(files.python, '');
  fs.writeFileSync(path.join(files.storage, 'dependencies.sha256'), fingerprint);
  fs.writeFileSync(files.solution, 'result = 42\n');
  const progress = path.join(files.folder, 'progress.sqlite3');
  fs.writeFileSync(progress, 'existing progress');

  const oldRuntime = path.join(files.storage, 'old-version', 'runtime');
  const trainer = loadExtension(files, {
    managed: true, version: 'new-version', activePython: files.python, extraPaths: [oldRuntime],
  });
  await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(trainer.calls.processes, []);
  assert.deepEqual(trainer.calls.interpreters, []);
  assert.deepEqual(trainer.calls.configuration.map(({ value }) => value), [[trainer.runtime]]);
  assert.equal(fs.readFileSync(files.solution, 'utf8'), 'result = 42\n');
  assert.equal(fs.readFileSync(progress, 'utf8'), 'existing progress');

  await trainer.open();
  await trainer.open();
  assert.deepEqual(trainer.calls.processes.map(({ args }) => args[0]), ['app.py']);
  assert.equal(trainer.calls.configuration.length, 1);
});

test('first launch from a legacy installation keeps the pre-workspace solution draft', async t => {
  const files = fixture(t);
  fs.mkdirSync(files.folder);
  fs.writeFileSync(files.solution, 'result = 42\n');
  const from = loadExtension(files);
  await from.open();
  fs.writeFileSync(files.solution, 'result = 43\n');
  await from.open();

  assert.equal(fs.readFileSync(path.join(files.storage, 'solution-before-upgrade.py'), 'utf8'), 'result = 42\n');
  assert.equal(fs.readFileSync(files.solution, 'utf8'), 'result = 43\n');
});

test('archives old drafts and closes restored copies of DataGym tabs', async t => {
  const files = fixture(t);
  fs.mkdirSync(files.folder);
  const draft = path.join(files.folder, 'solution-before-upgrade.py');
  fs.writeFileSync(draft, 'result = 42\n');
  const backup = { input: new TabInputText(draft) };
  const duplicate = { input: new TabInputText(files.solution), group: { viewColumn: 1 } };
  const solution = { input: new TabInputText(files.solution), group: { viewColumn: 2 } };
  const welcome = { label: 'Welcome' };
  const trainer = loadExtension(files, { managed: true, tabs: [backup, duplicate, solution, welcome] });
  await trainer.open();

  assert.deepEqual(trainer.calls.closedTabs, [backup, duplicate, welcome]);
  assert.equal(fs.existsSync(draft), false);
  assert.equal(fs.readFileSync(path.join(files.storage, 'solution-before-upgrade.py'), 'utf8'), 'result = 42\n');
});

test('recreating a missing managed environment reinstalls dependencies even with a matching marker', async t => {
  const files = fixture(t);
  fs.writeFileSync(path.join(files.storage, 'dependencies.sha256'), fingerprint);
  const trainer = loadExtension(files, { managed: true });
  await trainer.open();
  assert.ok(trainer.calls.processes.some(({ args }) => args[1] === 'pip'));
});

test('missing Python offers the official download and retry instructions', async t => {
  const trainer = loadExtension(fixture(t), { managed: true, pythonAvailable: false, useDownloadAction: true });
  await trainer.open();

  assert.deepEqual(trainer.calls.processes, []);
  assert.deepEqual(trainer.calls.interpreters, []);
  assert.equal(trainer.calls.panels, 0);
  assert.match(trainer.calls.errors[0].message, /Install Python 3\.11 or later.*DataGym: Open Trainer/);
  assert.equal(trainer.calls.errors[0].action, 'Download Python');
  assert.deepEqual(trainer.calls.urls, ['https://www.python.org/downloads/']);
});

test('Python API failure leaves the trainer usable and a later open retries IntelliSense', async t => {
  let fail = true;
  const files = fixture(t);
  const trainer = loadExtension(files, {
    managed: true,
    selectEnvironment() {
      if (fail) throw new Error('error from Python extension');
    },
  });
  await trainer.open();
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(trainer.calls.panels, 1);
  assert.deepEqual(trainer.calls.errors, []);
  assert.match(trainer.calls.warnings[0], /Enable or update.*Python and Pylance.*DataGym: Open Trainer/);
  assert.ok(trainer.calls.warnings[0].includes(files.python));
  fail = false;
  await trainer.open();
  assert.deepEqual(trainer.calls.interpreters, [[files.python, files.folder], [files.python, files.folder]]);
  assert.equal(trainer.calls.panels, 1);
  assert.equal(trainer.calls.processes.filter(({ args }) => args[0] === 'app.py').length, 1);
});

test('next exercise reuses the visible solution editor', async t => {
  const files = fixture(t);
  const lines = ['import pandas as pd', '# Example', 'result = '];
  const document = {
    uri: { toString: () => files.solution },
    languageId: 'python',
    lineCount: lines.length,
    lineAt: index => ({ text: lines[index] }),
  };
  let revealCount = 0;
  const editor = {
    document,
    viewColumn: 2,
    revealRange: () => { revealCount += 1; },
  };
  const trainer = loadExtension(files, { editor, managed: true });
  await trainer.open();
  revealCount = 0;
  assert.equal(trainer.commands.size, 5);

  await trainer.commands.get('datagym.next')();

  assert.equal(trainer.calls.documentOpens, 0);
  assert.equal(editor.selection.start.line, 2);
  assert.equal(editor.selection.start.character, lines[2].length);
  assert.equal(revealCount, 1);
});
