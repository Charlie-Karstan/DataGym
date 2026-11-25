'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const { setTimeout: delay } = require('node:timers/promises');

const root = process.env.DATAGYM_ACCEPTANCE_ROOT;
const details = {};
const dataGymId = 'charliekarstan.datagym-vscode';
const pythonId = 'ms-python.python';
const pylanceId = 'ms-python.vscode-pylance';
const pythonEnvsId = 'ms-python.vscode-python-envs';

function write(name, value) {
  const file = path.join(root, name + '.json');
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2));
  fs.renameSync(file + '.tmp', file);
}

async function until(description, check, timeout = 45000) {
  const end = Date.now() + timeout;
  do {
    const result = await check();
    if (result) return result;
    await delay(300);
  } while (Date.now() < end);
  throw new Error('Timed out waiting for ' + description);
}

async function complete(document, editor, line, expected, trigger) {
  const source = document.lineAt(line).text;
  const position = new vscode.Position(line, source.length);
  editor.selection = new vscode.Selection(position, position);
  await until(`${expected.join(', ')} after ${source}`, async () => {
    const list = await vscode.commands.executeCommand(
      'vscode.executeCompletionItemProvider', document.uri, position, trigger,
    );
    const labels = new Set((list?.items ?? []).map(item =>
      typeof item.label === 'string' ? item.label : item.label.label));
    return expected.every(label => labels.has(label));
  });
  return expected;
}

async function selectedInterpreter(uri) {
  const legacy = vscode.extensions.getExtension(pythonId);
  const api = await legacy.activate();
  await api.ready;
  if (vscode.workspace.getConfiguration('python', uri).get('useEnvironmentsExtension')) {
    const extension = vscode.extensions.getExtension(pythonEnvsId);
    assert.ok(extension, 'Python Environments must be enabled in this test mode');
    const manager = await extension.activate();
    assert.ok(extension.isActive);
    return (await manager.getEnvironment(uri))?.execInfo?.run?.executable;
  }
  return api.environments.getActiveEnvironmentPath(uri)?.path;
}

async function reopenFromProject(folder) {
  const file = path.join(folder.fsPath, '.vscode', 'settings.json');
  const settings = fs.readFileSync(file, 'utf8');
  const interpreter = await selectedInterpreter(folder);
  assert.ok(interpreter, 'The unrelated project must have a selected interpreter');
  await vscode.commands.executeCommand('datagym.open');
  assert.equal(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath, folder.fsPath);
  assert.equal(fs.readFileSync(file, 'utf8'), settings);
  assert.equal(await selectedInterpreter(folder), interpreter);
  write('project', { interpreter });
}

async function run(context) {
  const workspace = vscode.workspace.workspaceFile;
  const windowId = context.logUri.fsPath.split(path.sep).find(segment => /^window\d+$/.test(segment));
  const currentFolder = vscode.workspace.workspaceFolders?.[0]?.uri;
  const unrelated = path.join(root, 'unrelated');
  if (currentFolder?.fsPath === unrelated) {
    await reopenFromProject(currentFolder);
    return;
  }
  if (!workspace && !vscode.workspace.workspaceFolders?.length) {
    const launched = path.join(root, 'launched');
    if (!fs.existsSync(launched)) {
      const welcome = await until('VS Code’s Welcome tab', () => vscode.window.tabGroups.all
        .flatMap(group => group.tabs).find(tab => !tab.input && !tab.isDirty));
      assert.ok(windowId, 'The source VS Code window must have a log ID');
      fs.writeFileSync(launched, windowId);
      write('source', { windowId, welcome: welcome.label });
      await vscode.commands.executeCommand('datagym.open');
    }
    return;
  }
  assert.equal(path.basename(workspace?.fsPath ?? ''), 'DataGym.code-workspace');
  const sourceWindow = fs.readFileSync(path.join(root, 'launched'), 'utf8');
  assert.equal(windowId, sourceWindow, 'DataGym must reuse the named profile’s Welcome window');
  details.windowId = windowId;
  const folder = currentFolder;
  const uri = vscode.Uri.joinPath(folder, 'solution.py');
  details.initiallyTrusted = vscode.workspace.isTrusted;
  write('destination', { workspace: workspace.fsPath, ...details });
  if (!vscode.workspace.isTrusted) {
    assert.ok(fs.existsSync(path.join(folder.fsPath, '..', 'open-trainer')),
      'The launch request must still exist in Restricted Mode');
    assert.equal(vscode.extensions.getExtension(dataGymId)?.isActive ?? false, false);
    if (fs.existsSync(uri.fsPath)) await vscode.window.showTextDocument(uri);
    write('restricted', { workspace: workspace.fsPath, pendingLaunch: true });
    await until('Workspace Trust', () => vscode.workspace.isTrusted, 180000);
  }
  for (const id of [dataGymId, pythonId, pylanceId]) {
    const extension = vscode.extensions.getExtension(id);
    assert.ok(extension, id + ' must be installed and enabled in the destination');
    details[id] = extension.packageJSON.version;
  }

  // A single command in the original window must open the panel and solution in this host.
  const trainerTab = () => vscode.window.tabGroups.all.flatMap(group => group.tabs).find(tab =>
    tab.input instanceof vscode.TabInputWebview && tab.label === 'DataGym');
  await until('automatically opened trainer and solution.py', () =>
    trainerTab()
    && vscode.window.visibleTextEditors.some(editor => editor.document.uri.toString() === uri.toString()));
  const tabLabels = () => vscode.window.tabGroups.all.flatMap(group => group.tabs.map(tab => tab.label)).sort();
  await until('only the trainer and solution tabs', () => JSON.stringify(tabLabels()) === '["DataGym","solution.py"]');
  const document = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(document, { viewColumn: vscode.ViewColumn.Two });
  assert.equal(document.languageId, 'python');
  details.languageId = document.languageId;
  assert.equal(vscode.workspace.isTrusted, true);
  const managed = path.join(folder.fsPath, '..', 'venv');
  const python = path.join(managed, process.platform === 'win32' ? 'Scripts' : 'bin');
  const inManagedPython = executable =>
    Boolean(executable) && path.relative(python, path.dirname(executable)) === '';
  const legacy = vscode.extensions.getExtension(pythonId);
  const pylance = vscode.extensions.getExtension(pylanceId);
  assert.ok(legacy.isActive && pylance.isActive, 'Python and Pylance must be running');
  details.legacyInterpreter = legacy.exports.environments.getActiveEnvironmentPath(uri)?.path;
  details.managedInterpreter = await selectedInterpreter(uri);
  write('interpreters', details);

  const initial = document.getText();
  const replace = async text => {
    const edit = new vscode.WorkspaceEdit();
    edit.replace(uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)), text);
    assert.equal(await vscode.workspace.applyEdit(edit), true);
  };
  try {
    await replace('import numpy as np\nimport pandas as pd\nimport datagym\nresult = np.\n');
    details.numpy = await complete(document, editor, 3, ['arange', 'array'], '.');
    details.manualNumPy = await complete(document, editor, 3, ['arange', 'array']);
    await replace('import numpy as np\nimport pandas as pd\nimport datagym\nresult = np.ar\n');
    details.numpyPrefix = await complete(document, editor, 3, ['arange', 'array']);
    await replace('import numpy as np\nimport pandas as pd\nimport datagym\nresult = pd.\n');
    details.pandas = await complete(document, editor, 3, ['DataFrame'], '.');
    details.definitions = [];
    for (const [line, module] of ['numpy', 'pandas', 'datagym'].entries()) {
      const found = await vscode.commands.executeCommand(
        'vscode.executeDefinitionProvider', uri, new vscode.Position(line, 9));
      const searchRoot = module === 'datagym'
        ? path.join(vscode.extensions.getExtension(dataGymId).extensionPath, 'runtime') : managed;
      const resolved = found?.map(item => (item.targetUri || item.uri).fsPath)
        .find(file => file.startsWith(searchRoot + path.sep) && file.split(path.sep).includes(module));
      assert.ok(resolved, `Pylance must resolve ${module} under ${searchRoot}`);
      details.definitions.push(resolved);
    }
    assert.ok(inManagedPython(details.managedInterpreter),
      'The effective Python API must report the managed interpreter for solution.py');
    assert.ok(inManagedPython(details.legacyInterpreter),
      'The legacy Python API must also report the managed interpreter for solution.py');
    await replace('import numpy as np\nimport pandas as pd\nimport datagym\nresult = pd.DataFrame(np.arange(3))\n');
    await until('NumPy, pandas and DataGym imports without Pylance warnings', () =>
      !vscode.languages.getDiagnostics(uri).some(item => /missingImport|missingModuleSource/i.test(
        typeof item.code === 'object' ? String(item.code.value) : String(item.code))));
  } finally {
    await replace(initial);
    await document.save();
  }

  const oldDraft = 'result = "previous draft"\n';
  const legacyDraft = vscode.Uri.joinPath(folder, 'solution-before-upgrade.py');
  fs.writeFileSync(legacyDraft.fsPath, oldDraft);
  await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(legacyDraft), { preview: false });
  await vscode.window.showTextDocument(document, { viewColumn: vscode.ViewColumn.One, preview: false });
  assert.ok(tabLabels().includes('solution-before-upgrade.py'));
  await vscode.commands.executeCommand('datagym.open');
  assert.deepEqual(tabLabels(), ['DataGym', 'solution.py']);
  assert.equal(fs.existsSync(legacyDraft.fsPath), false);
  const archives = fs.readdirSync(path.dirname(folder.fsPath)).filter(name => name.startsWith('solution-before-upgrade'));
  assert.ok(archives.some(name => fs.readFileSync(path.join(folder.fsPath, '..', name), 'utf8') === oldDraft));
  details.tabs = tabLabels();

  if (details.initiallyTrusted) {
    const marker = path.join(folder.fsPath, '..', 'dependencies.sha256');
    const request = path.join(folder.fsPath, '..', 'open-trainer');
    await until('first launch request to be cleared', () => !fs.existsSync(request));
    const dependencyStamp = fs.statSync(marker).mtimeMs;
    const projectSettings = path.join(unrelated, '.vscode');
    fs.mkdirSync(projectSettings, { recursive: true });
    fs.writeFileSync(path.join(projectSettings, 'settings.json'), JSON.stringify({
      'python.analysis.extraPaths': ['./project-imports'],
    }));
    assert.equal(await vscode.window.tabGroups.close(trainerTab()), true);
    await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(unrelated), { forceNewWindow: true });
    await until('trainer reopened by the unrelated window', trainerTab);
    await until('unrelated project interpreter and settings check', () => fs.existsSync(path.join(root, 'project.json')));
    const { interpreter } = JSON.parse(fs.readFileSync(path.join(root, 'project.json'), 'utf8'));
    assert.equal(inManagedPython(interpreter), false, 'The unrelated project must keep its own interpreter');
    await until('second launch request to be cleared', () => !fs.existsSync(request));
    assert.equal(fs.statSync(marker).mtimeMs, dependencyStamp);
    assert.equal(document.getText(), initial);
    details.reopenedFromUnrelatedProject = true;
  }
  write('result', { ok: true, ...details });
}

exports.activate = context => {
  if (root) void run(context).catch(error => write('result', { ok: false, error: error.stack, ...details }));
};
