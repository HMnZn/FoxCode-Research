// Thin optional window. The same HTTP/SSE app also runs in a browser.
const { app, BrowserWindow } = require('electron')
app.whenReady().then(() => {
  const window = new BrowserWindow({ width: 1280, height: 900,
    backgroundColor: '#f8f9fb', webPreferences: { contextIsolation: true, nodeIntegration: false } })
  window.loadURL(process.env.FOXCODE_UI_URL || 'http://127.0.0.1:8877')
})
app.on('window-all-closed', () => app.quit())
