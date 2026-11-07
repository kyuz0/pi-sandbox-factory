const vscode = require('vscode');

exports.activate = async (context) => {
    if (context.workspaceState.get('pendantOpened')) return;
    await vscode.commands.executeCommand('pendant.chatView.focus');
    await context.workspaceState.update('pendantOpened', true);
};
