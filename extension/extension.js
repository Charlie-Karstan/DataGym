'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');
const { setTimeout: delay } = require('timers/promises');

const ROUTES = new Set([
  '/api/state', '/api/health',
  '/api/new', '/api/previous',
  '/api/hint', '/api/reveal',
  '/api/reset', '/api/import',
]);
const PYTHON_DOWNLOAD_URL = 'https://www.python.org/downloads/';
const PYTHON_EXTENSION = 'ms-python.python';
const PYTHON_ENVS_EXTENSION = 'ms-python.vscode-python-envs';
const UPGRADE_DRAFT = 'solution-before-upgrade.py';

class PythonRequiredError extends Error {}

let panel;
let server;
let root;
let storage;
let workspaceFolder;
let workspaceFile;
let solutionFile;
let trainerRequest;
let output;
let starting;
let openingTrainer;
let configuringIntelliSense;
let backendPort;
let saveTimer;

function managedPython() {
  return path.join(storage, 'venv', process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python');
}

function systemPython() {
  const configured = vscode.workspace.getConfiguration('datagym', workspaceFolder).get('pythonPath', '').trim();
  const candidates = configured
    ? [[configured, []]]
    : process.platform === 'win32'
      ? [['py', ['-3']], ['python', []]]
      : [['python3', []], ['/opt/homebrew/bin/python3', []], ['/usr/local/bin/python3', []], ['python', []]];

  for (const [command, prefix] of candidates) {
    const result = spawnSync(command, [...prefix, '-c',
      'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'],
      { timeout: 6000, windowsHide: true });
    if (result.status === 0) return { command, prefix };
  }
  throw new PythonRequiredError('Install Python 3.11 or later, then run DataGym: Open Trainer again. ' +
    'If Python is already installed, set datagym.pythonPath to its executable in VS Code Settings.');
}

function runProcess(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: root, windowsHide: true });
    child.stdout.on('data', data => output.append(data.toString()));
    child.stderr.on('data', data => output.append(data.toString()));
    child.on('error', reject);
    child.on('close', code => code === 0 ? resolve() : reject(
      new Error(`${path.basename(command)} exited with code ${code}. See Output → DataGym.`)));
  });
}

async function ensurePython() {
  const python = managedPython();
  const marker = path.join(storage, 'dependencies.sha256');
  if (!fs.existsSync(python)) {
    output.appendLine('Creating private Python environment...');
    const { command, prefix } = systemPython();
    fs.rmSync(marker, { force: true });
    await runProcess(command, [...prefix, '-m', 'venv', path.join(storage, 'venv')]);
  }

  const requirements = fs.readFileSync(path.join(root, 'requirements.txt'));
  const fingerprint = crypto.createHash('sha256').update(requirements).digest('hex');
  if (!fs.existsSync(marker) || fs.readFileSync(marker, 'utf8') !== fingerprint) {
    output.appendLine('Installing DataGym Python dependencies...');
    await runProcess(python, ['-m', 'pip', 'install', '--disable-pip-version-check',
      '-r', path.join(root, 'requirements.txt')]);
    fs.writeFileSync(marker, fingerprint);
  }
  return python;
}

async function api(route, body) {
  if (!ROUTES.has(route)) throw new Error(`Unsupported DataGym route: ${route}`);

  if (!backendPort) throw new Error('DataGym backend is not running.');
  const response = await fetch(`http://127.0.0.1:${backendPort}${route}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(7000),
  });

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`DataGym returned a non-JSON response (${response.status})`);
  }
  if (!response.ok) throw new Error(data.error || `DataGym error ${response.status}`);
  return data;
}

function launchBackend(python) {
  return new Promise((resolve, reject) => {
    let finished = false;
    let buffer = '';
    const child = spawn(python, ['app.py'], {
      cwd: root,
      env: {
        ...process.env,
        DATAGYM_PORT: '0',
        DATAGYM_WORKSPACE: workspaceFolder.fsPath,
        PYTHONUNBUFFERED: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    server = child;
    backendPort = undefined;
    const timer = setTimeout(() => {
      if (!finished) {
        finished = true;
        child.kill();
        reject(new Error('Python backend startup timed out. See Output → DataGym.'));
      }
    }, 20000);

    child.stdout.on('data', data => {
      const chunk = data.toString();
      output.append(chunk);
      buffer = (buffer + chunk).slice(-4096);
      const ready = buffer.match(/DATAGYM_READY (\d+)/);
      if (ready && !finished) {
        finished = true;
        clearTimeout(timer);
        backendPort = Number(ready[1]);
        resolve();
      }
    });
    child.stderr.on('data', data => output.append(data.toString()));
    child.on('error', error => {
      clearTimeout(timer);
      if (!finished) { finished = true; reject(error); }
    });
    child.on('exit', code => {
      clearTimeout(timer);
      if (server === child) output.appendLine(`DataGym backend exited: ${code}`);
      if (server === child) {
        server = undefined;
        backendPort = undefined;
      }
      if (!finished) { finished = true; reject(new Error(`Backend exited with code ${code}`)); }
    });
  });
}

async function ensureBackend() {
  if (server && backendPort && !server.killed) return;
  if (starting) return starting;

  starting = vscode.window.withProgress({
    location: vscode.ProgressLocation.Notification,
    title: 'Preparing DataGym',
    cancellable: false,
  }, async () => {
    const python = await ensurePython();
    await launchBackend(python);
  });
  try {
    await starting;
  } catch (error) {
    output.show(true);
    throw error;
  } finally {
    starting = undefined;
  }
}

function inTrainerWorkspace() {
  const { workspaceFile: current, workspaceFolders: folders } = vscode.workspace;
  return current?.toString() === workspaceFile.toString() && folders?.length === 1 &&
    folders[0].uri.toString() === workspaceFolder.toString();
}

function tabs() {
  return vscode.window.tabGroups.all.flatMap(group => group.tabs);
}

function isStartupTab(tab) {
  // VS Code exposes built-in Welcome and Getting Started pages without a tab input.
  return !tab.input && !tab.isDirty;
}

async function openTrainerWorkspace() {
  fs.mkdirSync(workspaceFolder.fsPath, { recursive: true });
  if (!fs.existsSync(workspaceFile.fsPath) && fs.existsSync(solutionFile.fsPath)) {
    // The backend starts each session with a new exercise. Keep the pre-workspace draft.
    try {
      fs.copyFileSync(solutionFile.fsPath, path.join(storage, UPGRADE_DRAFT),
        fs.constants.COPYFILE_EXCL);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
  }
  try {
    const settings = { 'python.analysis.extraPaths': [root] };
    fs.writeFileSync(workspaceFile.fsPath,
      JSON.stringify({ folders: [{ path: '.' }], settings }, null, 2) + '\n', { flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }

  // Keep the request across extension hosts and Workspace Trust transitions.
  fs.writeFileSync(trainerRequest, '');
  output.appendLine(`Opening the DataGym workspace at ${workspaceFile.fsPath}`);
  const reuseWindow = !vscode.workspace.workspaceFile && !vscode.workspace.workspaceFolders?.length &&
    tabs().every(isStartupTab);
  await vscode.commands.executeCommand('vscode.openFolder', workspaceFile, {
    forceReuseWindow: reuseWindow,
    forceNewWindow: !reuseWindow,
  });
}

async function tidyTrainerTabs() {
  const legacy = vscode.Uri.joinPath(workspaceFolder, UPGRADE_DRAFT);
  const restoredDraftTabs = tabs().filter(tab => tab.input instanceof vscode.TabInputText &&
    tab.input.uri.toString() === legacy.toString());
  if (restoredDraftTabs.some(tab => tab.isDirty)) {
    const draft = await vscode.workspace.openTextDocument(legacy);
    if (!await draft.save()) return;
  }
  if (restoredDraftTabs.length && !await vscode.window.tabGroups.close(restoredDraftTabs, true)) return;
  if (fs.existsSync(legacy.fsPath)) {
    const archive = path.join(storage, UPGRADE_DRAFT);
    const destination = fs.existsSync(archive)
      ? path.join(storage, `solution-before-upgrade-${crypto.randomUUID()}.py`)
      : archive;
    fs.renameSync(legacy.fsPath, destination);
  }
}

function isManagedInterpreter(executable) {
  // A virtual environment can have several Python entry points, often symlinked to base Python.
  return Boolean(executable) && path.relative(path.dirname(managedPython()), path.dirname(executable)) === '';
}

async function configurePython(signal) {
  const python = managedPython();
  const config = vscode.workspace.getConfiguration('python', solutionFile);
  const extraPaths = config.inspect('analysis.extraPaths')?.workspaceValue;
  if (extraPaths?.length !== 1 || extraPaths[0] !== root) {
    await config.update('analysis.extraPaths', [root], vscode.ConfigurationTarget.Workspace);
  }
  signal.throwIfAborted();
  const extension = vscode.extensions.getExtension(PYTHON_EXTENSION);
  const api = await extension?.activate();
  await api?.ready;
  signal.throwIfAborted();
  const environments = api?.environments;
  if (!environments?.updateActiveEnvironmentPath) throw new Error('Python environment API is unavailable.');

  const useEnvs = config.inspect('useEnvironmentsExtension');
  const enabled = useEnvs?.workspaceFolderValue ?? useEnvs?.workspaceValue ?? useEnvs?.globalValue;
  const manager = enabled === false ? undefined : vscode.extensions.getExtension(PYTHON_ENVS_EXTENSION);
  const modern = await manager?.activate();
  signal.throwIfAborted();
  const hasModernAPI = modern?.getEnvironment && modern.resolveEnvironment && modern.setEnvironment;
  const readLegacy = () => environments.getActiveEnvironmentPath(solutionFile)?.path;
  const readModern = async () => (await modern.getEnvironment(solutionFile))?.execInfo?.run?.executable;
  if (hasModernAPI) {
    if (!isManagedInterpreter(await readModern())) {
      const resolved = await modern.resolveEnvironment(vscode.Uri.file(python));
      signal.throwIfAborted();
      if (!isManagedInterpreter(resolved?.execInfo?.run?.executable)) {
        throw new Error(`Python Environments could not resolve ${python}.`);
      }
      await modern.setEnvironment(workspaceFolder, resolved);
    }
  } else if (enabled === true) {
    throw new Error('The Python Environments extension API is unavailable.');
  }

  signal.throwIfAborted();
  if (!isManagedInterpreter(readLegacy())) {
    await environments.updateActiveEnvironmentPath(python, workspaceFolder);
  }
  while (!signal.aborted) {
    const selected = readLegacy();
    const managed = hasModernAPI ? await readModern() : selected;
    signal.throwIfAborted();
    if (isManagedInterpreter(selected) && isManagedInterpreter(managed)) {
      output.appendLine(`Selected Python for solution.py: ${managed}`);
      return;
    }
    await delay(150, undefined, { signal });
  }
}

async function prepareIntelliSense() {
  const controller = new AbortController();
  let timer;
  try {
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        const error = new Error('Timed out confirming the managed interpreter for solution.py.');
        controller.abort(error);
        reject(error);
      }, 15000);
    });
    await Promise.race([configurePython(controller.signal), deadline]);
  } catch (error) {
    output.appendLine(`Python IntelliSense setup failed: ${error.message || error}`);
    vscode.window.showWarningMessage('DataGym could not configure Python IntelliSense. ' +
      'Enable or update the Microsoft Python and Pylance extensions, then run DataGym: Open Trainer again. ' +
      `You can also use Python: Select Interpreter in the DataGym window and enter ${managedPython()}.`);
  } finally {
    clearTimeout(timer);
  }
}

function configureIntelliSense() {
  configuringIntelliSense ??= prepareIntelliSense().finally(() => { configuringIntelliSense = undefined; });
  return configuringIntelliSense;
}

function assetUri(webview, filename) {
  const uri = vscode.Uri.file(path.join(root, 'static', filename));
  return webview.asWebviewUri(uri).toString();
}

function webviewBridge(nonce) {
  return `<script nonce="${nonce}">
  (() => {
    const vscode = acquireVsCodeApi();
    const originalFetch = window.fetch.bind(window);
    const pending = new Map();
    let sequence = 0;

    window.fetch = (url, options = {}) => {
      if (typeof url !== 'string' || !url.startsWith('/api/')) {
        return originalFetch(url, options);
      }
      const id = ++sequence;
      return new Promise((resolve, reject) => {
        let body;
        try {
          body = options.body ? JSON.parse(options.body) : undefined;
        } catch (error) {
          reject(error);
          return;
        }
        pending.set(id, { resolve, reject });
        vscode.postMessage({ type: 'api', id, route: url, body });
      });
    };

    window.addEventListener('message', event => {
      const message = event.data;
      if (message?.type === 'response') {
        const request = pending.get(message.id);
        if (!request) return;
        pending.delete(message.id);
        request.resolve({
          ok: message.ok,
          status: message.ok ? 200 : 400,
          json: async () => message.ok ? message.data : { error: message.error },
        });
      } else if (message?.type === 'answer') {
        document.getElementById('revealBtn')?.click();
      } else if (message?.type === 'hint') {
        document.getElementById('hintBtn')?.click();
      }
    });
  })();
  </script>`;
}

function renderHtml(webview) {
  const nonce = crypto.randomBytes(18).toString('base64');
  const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
  const assets = html
    .replace(/href=["']\/static\/style\.css["']/g, `href="${assetUri(webview, 'style.css')}"`)
    .replace(/src=["']\/static\/app\.js["']/g, `src="${assetUri(webview, 'app.js')}"`);

  const csp = `default-src 'none'; img-src ${webview.cspSource} data:; ` +
    `style-src ${webview.cspSource}; ` +
    `script-src ${webview.cspSource} 'nonce-${nonce}';`;
  return assets.replace('</head>',
    `<meta http-equiv="Content-Security-Policy" content="${csp}">\n${webviewBridge(nonce)}\n</head>`);
}

async function positionAtResult() {
  const key = solutionFile.toString();
  let editor = vscode.window.visibleTextEditors.find(
  candidate =>
    candidate.document.uri.toString() === key &&
    candidate.viewColumn === vscode.ViewColumn.Two
  );

  let document = editor?.document ?? await vscode.workspace.openTextDocument(solutionFile);
  if (document.languageId !== 'python') {
    document = await vscode.languages.setTextDocumentLanguage(document, 'python');
    editor = undefined;
  }
  if (!editor) {
    editor = await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.Two,
      preserveFocus: true,
      preview: false,
    });
  }

  let lineNumber = document.lineCount - 1;
  for (let i = lineNumber; i >= 0; i--) {
    if (document.lineAt(i).text.trimStart().startsWith('result =')) {
      lineNumber = i;
      break;
    }
  }

  const line = document.lineAt(lineNumber);
  const cursor = new vscode.Position(lineNumber, line.text.length);
  editor.selection = new vscode.Selection(cursor, cursor);
  editor.revealRange(
    new vscode.Range(cursor, cursor),
    vscode.TextEditorRevealType.InCenterIfOutsideViewport
  );
}

async function saveSolutionBeforeNavigation() {
  const document = vscode.workspace.textDocuments?.find(
    doc => doc.uri.fsPath === solutionFile.fsPath
  );

  if (document?.isDirty && !(await document.save())) {
    throw new Error('Could not save solution.py before navigating.');
  }
}

async function handleWebviewRequest(message) {
  if (message.route === '/api/new' || message.route === '/api/previous') {
    await saveSolutionBeforeNavigation();
  }
  if (message?.type !== 'api' || !Number.isSafeInteger(message.id)) return;
  try {
    const data = await api(message.route, message.body);
    await panel?.webview.postMessage({ type: 'response', id: message.id, ok: true, data });
  if (
    message.route === '/api/new' ||
    message.route === '/api/previous'
  ) {
    await positionAtResult();
  }
  } catch (error) {
    await panel?.webview.postMessage({
      type: 'response', id: message.id, ok: false,
      error: String(error.message || error),
    });
  }
}

async function openTrainer() {
  await ensureBackend();
  try {
    await tidyTrainerTabs();
  } catch (error) {
    output.appendLine(`Could not archive the old solution draft: ${error.message || error}`);
  }
  if (panel) {
    panel.reveal(undefined, true);
  } else {
    await vscode.commands.executeCommand('vscode.setEditorLayout', {
      orientation: 1,
      groups: [{ size: 0.8 }, { size: 0.2 }],
    });
    panel = vscode.window.createWebviewPanel('datagym', 'DataGym', vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.file(path.join(root, 'static'))],
    });
    panel.webview.html = renderHtml(panel.webview);
    panel.webview.onDidReceiveMessage(handleWebviewRequest);
    panel.onDidDispose(() => { panel = undefined; });
  }
  await configureIntelliSense();
  await positionAtResult();
  const extraTabs = tabs().filter(tab => isStartupTab(tab) || (
    tab.input instanceof vscode.TabInputText && tab.input.uri.toString() === solutionFile.toString() &&
    tab.group.viewColumn !== vscode.ViewColumn.Two
  ));
  if (extraTabs.length) await vscode.window.tabGroups.close(extraTabs, true);
}

function requestTrainer() {
  openingTrainer ??= (async () => {
    try {
      if (inTrainerWorkspace()) {
        if (!vscode.workspace.isTrusted) return;
        await openTrainer();
        fs.rmSync(trainerRequest, { force: true });
        output.appendLine('DataGym trainer and solution.py opened.');
      } else {
        await openTrainerWorkspace();
      }
    } catch (error) {
      const message = `DataGym: ${error.message || error}`;
      if (error instanceof PythonRequiredError) {
        const action = 'Download Python';
        if (await vscode.window.showErrorMessage(message, action) === action) {
          await vscode.env.openExternal(vscode.Uri.parse(PYTHON_DOWNLOAD_URL));
        }
      } else {
        vscode.window.showErrorMessage(message);
      }
    }
  })().finally(() => { openingTrainer = undefined; });
  return openingTrainer;
}

async function runCommand(route) {
  if (!inTrainerWorkspace() || !vscode.workspace.isTrusted) return;
  try {
    await openingTrainer;
    if (route === '/api/reveal' || route === '/api/hint') {
      await requestTrainer();
      await panel?.webview.postMessage({ type: route === '/api/reveal' ? 'answer' : 'hint' });
      return;
    }
    await ensureBackend();
    if (route === '/api/new' || route === '/api/previous') {
      await saveSolutionBeforeNavigation();
    }
    const data = await api(route, {});
    if (route === '/api/new') await positionAtResult();
    await panel?.webview.postMessage({ type: 'state', data });
  } catch (error) {
    vscode.window.showErrorMessage(`DataGym: ${error.message || error}`);
  }
}

function activate(context) {
  root = path.join(context.extensionPath, 'runtime');
  storage = context.globalStorageUri.fsPath;
  workspaceFolder = vscode.Uri.file(path.join(storage, 'workspace'));
  workspaceFile = vscode.Uri.joinPath(workspaceFolder, 'DataGym.code-workspace');
  solutionFile = vscode.Uri.joinPath(workspaceFolder, 'solution.py');
  trainerRequest = path.join(storage, 'open-trainer');
  fs.mkdirSync(storage, { recursive: true });
  output = vscode.window.createOutputChannel('DataGym');
  output.appendLine(`DataGym user data: ${storage}`);
  context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => {
    if (event.document.uri.fsPath !== solutionFile.fsPath) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      event.document.save().catch(error => output.appendLine(`Auto-save failed: ${error.message}`));
    }, 450);
  }));
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand('datagym.open', requestTrainer));

  for (const [command, route] of [
    ['datagym.next', '/api/new'],
    ['datagym.answer', '/api/reveal'],
    ['datagym.hint', '/api/hint'],
    ['datagym.reset', '/api/reset'],
  ]) {
    context.subscriptions.push(
      vscode.commands.registerCommand(command, () => runCommand(route))
    );
  }

  if (inTrainerWorkspace()) {
    const launchPending = () => {
      if (inTrainerWorkspace() && vscode.workspace.isTrusted && fs.existsSync(trainerRequest)) {
        void requestTrainer();
      }
    };
    const reportWatchError = error => output.appendLine(`Could not watch trainer launch requests: ${error.message}`);
    try {
      const watcher = fs.watch(storage, { persistent: false }, (_event, filename) => {
        if (!filename || filename === path.basename(trainerRequest)) launchPending();
      });
      watcher.on('error', reportWatchError);
      context.subscriptions.push({ dispose: () => watcher.close() });
    } catch (error) {
      reportWatchError(error);
    }
    context.subscriptions.push(vscode.window.onDidChangeWindowState(({ focused }) => {
      if (focused) launchPending();
    }));
    const onTrusted = () => {
      if (!inTrainerWorkspace()) return;
      output.appendLine(`Managed workspace active (trusted: ${vscode.workspace.isTrusted}).`);
      if (fs.existsSync(trainerRequest)) launchPending();
      else if (vscode.workspace.isTrusted && fs.existsSync(managedPython())) void configureIntelliSense();
    };
    context.subscriptions.push(vscode.workspace.onDidGrantWorkspaceTrust(onTrusted));
    onTrusted();
  }
}

function deactivate() {
  clearTimeout(saveTimer);
  const child = server;
  server = undefined;
  if (child && !child.killed) child.kill();
}

module.exports = { activate, deactivate };
