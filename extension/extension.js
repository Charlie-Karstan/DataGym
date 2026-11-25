'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');

const ROUTES = new Set([
  '/api/state', '/api/health',
  '/api/new', '/api/previous',
  '/api/hint', '/api/reveal',
  '/api/reset', '/api/import',
]);
const PYTHON_DOWNLOAD_URL = 'https://www.python.org/downloads/';

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
      output.appendLine(`DataGym backend exited: ${code}`);
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

async function openTrainerWorkspace() {
  fs.mkdirSync(workspaceFolder.fsPath, { recursive: true });
  if (!fs.existsSync(workspaceFile.fsPath) && fs.existsSync(solutionFile.fsPath)) {
    // The backend starts each session with a new exercise. Keep the pre-workspace draft.
    try {
      fs.copyFileSync(solutionFile.fsPath, path.join(workspaceFolder.fsPath, 'solution-before-upgrade.py'),
        fs.constants.COPYFILE_EXCL);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
  }
  try {
    fs.writeFileSync(workspaceFile.fsPath, JSON.stringify({ folders: [{ path: '.' }] }, null, 2) + '\n',
      { flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }

  // An existing DataGym window can receive the request when VS Code focuses it.
  fs.writeFileSync(trainerRequest, '');
  const reuseWindow = !vscode.workspace.workspaceFile && !vscode.workspace.workspaceFolders?.length &&
    !vscode.window.tabGroups.all.some(group => group.tabs.length);
  await vscode.commands.executeCommand('vscode.openFolder', workspaceFile, {
    forceReuseWindow: reuseWindow,
    forceNewWindow: !reuseWindow,
  });
}

async function configurePython() {
  try {
    const analysis = vscode.workspace.getConfiguration('python.analysis', workspaceFolder);
    const extraPaths = analysis.inspect('extraPaths')?.workspaceValue;
    if (extraPaths?.length !== 1 || extraPaths[0] !== root) {
      await analysis.update('extraPaths', [root], vscode.ConfigurationTarget.Workspace);
    }

    const extension = vscode.extensions.getExtension('ms-python.python');
    const api = await extension?.activate();
    const environments = api?.environments;
    if (!environments?.updateActiveEnvironmentPath) throw new Error('Python environment API is unavailable.');
    const python = managedPython();
    if (environments.getActiveEnvironmentPath(workspaceFolder)?.path !== python) {
      await environments.updateActiveEnvironmentPath(python, workspaceFolder);
    }
  } catch (error) {
    output.appendLine(`Python IntelliSense setup failed: ${error.message || error}`);
    vscode.window.showWarningMessage('DataGym could not configure Python IntelliSense. ' +
      'Enable or update the Microsoft Python and Pylance extensions, then run DataGym: Open Trainer again. ' +
      `You can also use Python: Select Interpreter in the DataGym window and enter ${managedPython()}.`);
  }
}

function configureIntelliSense() {
  configuringIntelliSense ??= configurePython().finally(() => { configuringIntelliSense = undefined; });
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

  if (!editor) {
    const document = await vscode.workspace.openTextDocument(solutionFile);
    editor = await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.Two,
      preserveFocus: true,
      preview: false,
    });
  }

  const document = editor.document;
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
  // Python extension activation must not delay the trainer or its backend.
  configureIntelliSense();
  if (panel) {
    panel.reveal(undefined, true);
    return;
  }
  await vscode.commands.executeCommand('vscode.setEditorLayout', {
  orientation: 1,
  groups: [
    { size: 0.8 },
    { size: 0.2 },
  ],
  });

  panel = vscode.window.createWebviewPanel('datagym', 'DataGym', vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.file(path.join(root, 'static'))],
  });
  panel.webview.html = renderHtml(panel.webview);
  panel.webview.onDidReceiveMessage(handleWebviewRequest);
  panel.onDidDispose(() => { panel = undefined; });
  await positionAtResult();
}

function requestTrainer() {
  openingTrainer ??= (async () => {
    try {
      if (inTrainerWorkspace()) {
        fs.rmSync(trainerRequest, { force: true });
        await openTrainer();
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
  if (!inTrainerWorkspace()) return;
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
    context.subscriptions.push(vscode.window.onDidChangeWindowState(({ focused }) => {
      if (focused && fs.existsSync(trainerRequest) && inTrainerWorkspace()) void requestTrainer();
    }));
    if (fs.existsSync(trainerRequest)) {
      void requestTrainer();
    } else if (fs.existsSync(managedPython())) {
      configureIntelliSense();
    }
  }
}

function deactivate() {
  clearTimeout(saveTimer);
  if (server && !server.killed) server.kill();
}

module.exports = { activate, deactivate };
