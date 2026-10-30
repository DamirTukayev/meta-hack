// Minimal Chrome DevTools Protocol driver (no dependencies, needs Node 22+ and Google Chrome): launch headless Chrome, evaluate JS, click, screenshot. Used by capture_demo.mjs to make the README images.
import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
export async function launch(width = 1440, height = 900, profile = `/tmp/orbitroute-chrome-profile-${process.pid}`) { // a fresh profile every time: a language chosen in one capture must not stay in the next
  const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9333', `--user-data-dir=${profile}`, `--window-size=${width},${height}`, '--hide-scrollbars', '--force-device-scale-factor=1', '--no-first-run', 'about:blank'], { stdio: 'ignore' })
  let targets
  for (let i = 0; i < 50; i++) {
    try { targets = await (await fetch('http://127.0.0.1:9333/json')).json(); if (targets.find((t) => t.type === 'page')) break } catch {}
    await new Promise((r) => setTimeout(r, 200))
  }
  const page = targets.find((t) => t.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((r) => (ws.onopen = r))
  let id = 0
  const pending = new Map()
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id) } }
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(d.error.message)) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params })) })
  await send('Page.enable'); await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false })
  const api = {
    send,
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    goto: async (url) => { await send('Page.navigate', { url }); await api.sleep(1500) },
    eval: async (expression) => { const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception?.description ?? r.exceptionDetails)); return r.result.value },
    click: async (x, y) => { for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 }); await api.sleep(150) },
    shot: async (path, { format = 'png', quality = 80, clip } = {}) => { const r = await send('Page.captureScreenshot', { format, quality: format === 'jpeg' ? quality : undefined, clip }); writeFileSync(path, Buffer.from(r.data, 'base64')) },
    close: async () => { try { await send('Browser.close') } catch {} ; proc.kill() },
  }
  return api
}
