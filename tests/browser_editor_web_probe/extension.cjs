// Browser worker test: no file picker grants, clipboard reads, or real credentials.
const vscode = require('vscode');
exports.activate = async () => {
  const root = vscode.workspace.workspaceFolders[0].uri;
  const config = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, 'browser-editor-probe.json'))));
  const results = {uiKind: vscode.env.uiKind, hasNodeProcess: typeof process !== 'undefined'};
  async function probe(name, operation) {
    try { results[name] = {ok: true, value: String(await operation())}; }
    catch (error) { results[name] = {ok: false, error: String(error.message)}; }
  }
  for (const path of config.hostFiles) {
    for (const scheme of ['file', 'vscode-local']) {
      await probe(scheme + ':' + path, async () => new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.from({scheme, path}))));
    }
    await probe('fetch:' + path, async () => (await fetch('file://' + path)).text());
  }
  await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(root, 'browser-editor-web-probe-results.json'), new TextEncoder().encode(JSON.stringify(results, null, 2)));
};
