// Records the README demo: frames of a one-click run and of the drive replay, plus a full-size screenshot of the result.
// Needs the app running on http://localhost:8000 (npm run build first). Usage: node scripts/capture_demo.mjs [frames-dir]
// Then: uv run python scripts/make_gif.py [frames-dir]
import { mkdirSync, rmSync } from 'node:fs'
import { launch } from './cdp.mjs'

const dir = process.argv[2] ?? 'scratch/frames'
rmSync(dir, { recursive: true, force: true })
mkdirSync(dir, { recursive: true })
const b = await launch(1440, 900)
let n = 0
const frame = async (tag = '') => b.shot(`${dir}/f${String(n++).padStart(3, '0')}${tag}.jpg`, { format: 'jpeg', quality: 72 })

await b.goto('http://localhost:8000/')
await b.sleep(1200)
await frame('_hold')                     // the welcome card
await b.eval(`[...document.querySelectorAll('button')].find(x => /try it with/i.test(x.innerText)).click()`)
const t0 = Date.now()
let done = false
while (Date.now() - t0 < 40000 && !done) {
  await frame()
  done = await b.eval(`/verified/i.test(document.querySelector('.result')?.innerText ?? '') && !!document.querySelector('.drive')`)
  await b.sleep(250)
}
await b.eval('window.scrollTo(0, 0)')
await b.sleep(700)
await b.shot(`${dir}/result.png`)           // full-size screenshot of the finished plan
await frame('_hold')
await b.eval(`[...document.querySelectorAll('button')].find(x => /replay the drive/i.test(x.innerText)).click()`)
for (let i = 0; i < 22; i++) { await frame(); await b.sleep(180) }
await frame('_hold')
await b.close()
console.log(`captured ${n} frames in ${dir}`)
