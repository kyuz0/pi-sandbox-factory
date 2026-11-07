// Disposable test extension: attempts access to synthetic files only.
const vscode = require('vscode');
const fs = require('node:fs/promises');
exports.activate = async () => {
  const config = JSON.parse(await fs.readFile('/workspace/browser-editor-probe.json', 'utf8'));
  const results = {};
  async function probe(name, operation) {
    try { results[name] = {ok: true, value: String(await operation())}; }
    catch (error) { results[name] = {ok: false, error: String(error.message)}; }
  }
  for (const path of config.hostFiles) {
    await probe('node:' + path, () => fs.readFile(path, 'utf8'));
    for (const scheme of ['file', 'vscode-local', 'vscode-userdata']) {
      const uri = vscode.Uri.from({scheme, path});
      await probe(scheme + ':' + path, async () => Buffer.from(await vscode.workspace.fs.readFile(uri)).toString());
      await probe('document:' + scheme + ':' + path, async () => (await vscode.workspace.openTextDocument(uri)).getText());
    }
  }
  await probe('workspace-write', async () => { await fs.writeFile('/workspace/editor-probe-output.txt', 'WORKSPACE_WRITE_OK'); return 'ok'; });
  await probe('readonly-read', () => fs.readFile('/mnt/reference/reference.txt', 'utf8'));
  await probe('readonly-write', () => fs.writeFile('/mnt/reference/must-not-exist', 'bad'));
  const commands = await vscode.commands.getCommands();
  results.localTerminalCommandPresent = commands.includes('workbench.action.terminal.newLocal');
  if (results.localTerminalCommandPresent) {
    await probe('local-terminal', () => vscode.commands.executeCommand('workbench.action.terminal.newLocal'));
    const terminal = vscode.window.activeTerminal;
    if (terminal) {
      // Even if a terminal appears, its write must not reach the unmounted host directory.
      terminal.sendText(`printf TERMINAL_ESCAPED > '${config.hostMarker}'`);
      await new Promise(resolve => setTimeout(resolve, 1000));
      terminal.dispose();
    }
  }
  results.remoteName = vscode.env.remoteName;
  results.pendantActive = vscode.extensions.getExtension('cdervis.vscode-pi')?.isActive;
  await fs.writeFile('/workspace/browser-editor-probe-results.json', JSON.stringify(results, null, 2));
};
