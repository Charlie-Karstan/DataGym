'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const projectRoot = path.resolve(__dirname, '..');

function loadExtension({ editor }) {
  const commands = new Map();
  let documentOpens = 0;
  const vscode = {
    workspace: {
      workspaceFolders: [{ uri: { fsPath: projectRoot } }],
      getConfiguration: () => ({ get: () => '' }),
      openTextDocument: async () => {
        documentOpens += 1;
        throw new Error('An existing editor should be reused');
      },
    },
    window: {
      visibleTextEditors: [editor],
      createOutputChannel: () => ({ append() {}, appendLine() {}, dispose() {} }),
      showErrorMessage: message => { throw new Error(message); },
    },
    commands: {
      registerCommand: (name, handler) => {
        commands.set(name, handler);
        return { dispose() {} };
      },
    },
    Uri: { file: fsPath => ({ fsPath, toString: () => fsPath }) },
    ViewColumn: { Two: 2 },
    Position: class { constructor(line, character) { Object.assign(this, { line, character }); } },
    Selection: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    TextEditorRevealType: { InCenterIfOutsideViewport: 1 },
  };
  const context = {
    require: name => name === 'vscode' ? vscode : require(name),
    module: { exports: {} },
    process,
    setTimeout,
    AbortSignal,
    fetch: async url => ({
      ok: true,
      status: 200,
      json: async () => url.endsWith('/api/health')
        ? { ok: true, service: 'DataGym' }
        : { ok: true },
    }),
  };
  const code = fs.readFileSync(path.join(projectRoot, 'extension', 'extension.js'), 'utf8');
  vm.runInNewContext(code, context, { filename: 'extension.js' });
  context.module.exports.activate({ subscriptions: [] });
  return { commands, getDocumentOpens: () => documentOpens };
}

test('next exercise reuses the visible solution editor', async () => {
  const location = path.join(projectRoot, 'workspace', 'solution.py');
  const lines = ['import pandas as pd', '# Example', 'result = '];
  const document = {
    uri: { toString: () => location },
    lineCount: lines.length,
    lineAt: index => ({ text: lines[index] }),
  };
  let revealCount = 0;
  const editor = {
  document,
  viewColumn: 2,
  revealRange: () => { revealCount += 1; },
  };;
  const extension = loadExtension({ editor });
  assert.equal(extension.commands.size, 5);

  await extension.commands.get('datagym.next')();

  assert.equal(extension.getDocumentOpens(), 0);
  assert.equal(editor.selection.start.line, 2);
  assert.equal(editor.selection.start.character, lines[2].length);
  assert.equal(revealCount, 1);
});
