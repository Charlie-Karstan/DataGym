'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const PORT = 8765;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const ROUTES = new Set([
  '/api/state', '/api/health', '/api/new', '/api/hint',
  '/api/reveal', '/api/reset', '/api/import',
]);

let panel;
let server;
let ownsServer = false;
let root;
let output;
let starting;

function findRoot() {
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const dir = folder.uri.fsPath;
    const files = ['app.py', 'static/index.html', 'datagym/ui_app.py'];
    if (files.every(file => fs.existsSync(path.join(dir, file)))) return dir;
  }
  throw new Error('Open the DataGym project folder in VS Code (the folder with app.py).');
}

function pythonExecutable() {
  const configured = vscode.workspace.getConfiguration('datagym').get('pythonPath', '').trim();
  if (configured) return configured;

  const relativePath = process.platform === 'win32'
    ? ['.venv', 'Scripts', 'python.exe']
    : ['.venv', 'bin', 'python'];
  const python = path.join(root, ...relativePath);
  if (!fs.existsSync(python)) {
    throw new Error(`Python environment not found: ${python}. See START_HERE.md.`);
  }
  return python;
}

async function api(route, body) {
  if (!ROUTES.has(route)) throw new Error(`Unsupported DataGym route: ${route}`);

  const response = await fetch(BASE_URL + route, {
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

async function backendRunning() {
  try {
    const health = await api('/api/health');
    return health.ok === true && health.service === 'DataGym';
  } catch {
    return false;
  }
}

function launchBackend() {
  server = spawn(pythonExecutable(), ['app.py'], {
    cwd: root,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  ownsServer = true;

  server.stdout.on('data', data => output.append(data.toString()));
  server.stderr.on('data', data => output.append(data.toString()));
  server.on('error', error => output.appendLine(`Backend failed: ${error.message}`));
  server.on('exit', code => {
    output.appendLine(`DataGym Python process exited: ${code}`);
    server = undefined;
    ownsServer = false;
  });
}

async function ensureBackend() {
  if (await backendRunning()) return;
  if (starting) return starting;

  starting = (async () => {
    launchBackend();
    for (let attempt = 0; attempt < 50; attempt++) {
      if (await backendRunning()) return;
      if (!server) break;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw new Error('Backend did not start. See Output → DataGym; port 8765 may be occupied.');
  })();

  try {
    await starting;
  } finally {
    starting = undefined;
  }
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
  const uri = vscode.Uri.file(path.join(root, 'workspace', 'solution.py'));
  const key = uri.toString();
  let editor = vscode.window.visibleTextEditors.find(
  candidate =>
    candidate.document.uri.toString() === key &&
    candidate.viewColumn === vscode.ViewColumn.Two
  );

  if (!editor) {
    const document = await vscode.workspace.openTextDocument(uri);
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

async function handleWebviewRequest(message) {
  if (message?.type !== 'api' || !Number.isSafeInteger(message.id)) return;
  try {
    const data = await api(message.route, message.body);
    await panel?.webview.postMessage({ type: 'response', id: message.id, ok: true, data });
    if (message.route === '/api/new') await positionAtResult();
  } catch (error) {
    await panel?.webview.postMessage({
      type: 'response', id: message.id, ok: false,
      error: String(error.message || error),
    });
  }
}

async function openTrainer() {
  root = findRoot();
  await ensureBackend();
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

async function runCommand(route) {
  try {
    root = findRoot();
    await ensureBackend();
    if (route === '/api/reveal' || route === '/api/hint') {
      await openTrainer();
      await panel?.webview.postMessage({ type: route === '/api/reveal' ? 'answer' : 'hint' });
      return;
    }
    const data = await api(route, {});
    if (route === '/api/new') await positionAtResult();
    await panel?.webview.postMessage({ type: 'state', data });
  } catch (error) {
    vscode.window.showErrorMessage(`DataGym: ${error.message || error}`);
  }
}

function activate(context) {
  output = vscode.window.createOutputChannel('DataGym');
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand('datagym.open', async () => {
    try {
      await openTrainer();
    } catch (error) {
      vscode.window.showErrorMessage(`DataGym: ${error.message || error}`);
    }
  }));

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
}

function deactivate() {
  if (ownsServer && server && !server.killed) server.kill();
}

module.exports = { activate, deactivate };
