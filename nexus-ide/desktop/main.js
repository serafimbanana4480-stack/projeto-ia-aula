const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs/promises');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);
const WEB_URL = process.env.NEXUS_WEB_URL || 'http://localhost:3000';

function resolveWithinRoot(root, target = '.') {
  const rootPath = path.resolve(root);
  const resolved = path.resolve(rootPath, target);
  const relative = path.relative(rootPath, resolved);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`Path ${resolved} is outside workspace root ${rootPath}`);
  }
  return resolved;
}

async function listDirectory(root, target = '.', recursive = true) {
  const fullPath = resolveWithinRoot(root, target);
  const stat = await fs.stat(fullPath);
  if (!stat.isDirectory()) {
    throw new Error(`Path ${target} is not a directory`);
  }

  const items = [];
  async function walk(currentPath, basePath) {
    const entries = await fs.readdir(currentPath, { withFileTypes: true });
    for (const entry of entries) {
      const entryFullPath = path.join(currentPath, entry.name);
      const relative = path.relative(basePath, entryFullPath) || entry.name;
      const entryStat = await fs.stat(entryFullPath);
      const node = {
        path: relative,
        name: entry.name,
        type: entry.isDirectory() ? 'directory' : 'file',
        size: entry.isDirectory() ? 0 : entryStat.size,
        children: [],
      };
      items.push(node);
      if (recursive && entry.isDirectory()) {
        await walk(entryFullPath, basePath);
      }
    }
  }

  await walk(fullPath, fullPath);
  return { path: fullPath, count: items.length, items };
}

async function readFile(root, target) {
  const fullPath = resolveWithinRoot(root, target);
  const content = await fs.readFile(fullPath, 'utf8');
  return { path: fullPath, content, size: content.length };
}

async function writeFile(root, target, content) {
  const fullPath = resolveWithinRoot(root, target);
  await fs.mkdir(path.dirname(fullPath), { recursive: true });
  await fs.writeFile(fullPath, content, 'utf8');
  return { path: fullPath, written: true, size: content.length };
}

async function executeCommand(root, command, timeoutSeconds = 30) {
  const fullPath = resolveWithinRoot(root, '.');
  const timeoutMs = timeoutSeconds * 1000;
  const startedAt = Date.now();
  let stdout = '';
  let stderr = '';
  let exitCode = 0;
  let timedOut = false;

  try {
    const result = await execFileAsync(command, {
      cwd: fullPath,
      shell: true,
      timeout: timeoutMs,
      maxBuffer: 1024 * 1024 * 8,
      env: process.env,
    });
    stdout = result.stdout ?? '';
    stderr = result.stderr ?? '';
  } catch (error) {
    stdout = error.stdout ?? '';
    stderr = error.stderr ?? error.message ?? 'Command failed';
    exitCode = typeof error.code === 'number' ? error.code : 1;
    timedOut = error.killed && error.signal === 'SIGTERM';
  }

  return {
    execution_id: `exec-${Date.now()}`,
    command,
    stdout,
    stderr,
    exit_code: exitCode,
    timed_out: timedOut,
    duration_ms: Date.now() - startedAt,
    risk_level: 'desktop',
  };
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1680,
    height: 1080,
    backgroundColor: '#0b0f17',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadURL(WEB_URL);
}

app.whenReady().then(() => {
  ipcMain.handle('workspace:select', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
      title: 'Select workspace folder',
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
  });

  ipcMain.handle('workspace:list', async (_event, { root, path: target = '.', recursive = true }) => {
    return listDirectory(root, target, recursive);
  });

  ipcMain.handle('workspace:read', async (_event, { root, path: target }) => {
    return readFile(root, target);
  });

  ipcMain.handle('workspace:write', async (_event, { root, path: target, content }) => {
    return writeFile(root, target, content);
  });

  ipcMain.handle('workspace:exec', async (_event, { root, command, timeoutSeconds }) => {
    return executeCommand(root, command, timeoutSeconds);
  });

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
