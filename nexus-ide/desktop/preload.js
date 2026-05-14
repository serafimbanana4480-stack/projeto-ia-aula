const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nexusDesktop', {
  selectDirectory: () => ipcRenderer.invoke('workspace:select'),
  listFiles: (root, target = '.', recursive = true) => ipcRenderer.invoke('workspace:list', { root, path: target, recursive }),
  readFile: (root, target) => ipcRenderer.invoke('workspace:read', { root, path: target }),
  writeFile: (root, target, content) => ipcRenderer.invoke('workspace:write', { root, path: target, content }),
  executeCommand: (root, command, timeoutSeconds = 30) => ipcRenderer.invoke('workspace:exec', { root, command, timeoutSeconds }),
});
