// Screenshot of a freely clicked run: 16 orders spread over the road graph of one sample, the way a user clicking around would place them.
// Needs the app on http://localhost:8000. Usage: node scripts/capture_cutoff.mjs SAMPLE OUT.png   (for example: houston-harvey-b docs/flood-cutoff.png)
import { launch } from './cdp.mjs'
const sample = process.argv[2], out = process.argv[3]
// 1. spread points over the road graph of the sample (an auto run gives us graph nodes and a sensible depot)
const res = await fetch('http://localhost:8000/api/run', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ sample, request: 'by 14:00, avoid the flooded areas', auto_orders: 5, trucks: 3 }) })
const text = await res.text()
let nodes = null, depot = null
for (const block of text.split('\n\n')) {
  const m = block.match(/^data: (.*)$/m); if (!m) continue
  const d = JSON.parse(m[1])
  if (d.type === 'perception') nodes = d.data.graph.nodes
  if (d.type === 'scenario') depot = d.data.depot
}
console.log('graph nodes', nodes?.length, 'depot', depot)
const picked = []
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1])
let cand = nodes.map(n => (Array.isArray(n) ? n : [n.x, n.y]))
picked.push(cand[0])
while (picked.length < 16) { let best = null, bd = -1; for (const c of cand) { const dd = Math.min(...picked.map(p => dist(p, c))); if (dd > bd) { bd = dd; best = c } } picked.push(best) }
// 2. drive the UI like a user
const b = await launch(1440, 1200)
await b.goto('http://localhost:8000/'); await b.sleep(1200)
await b.eval(`(() => { const s = document.querySelector('select'); s.value = '${sample}'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`)
await b.sleep(800)
await b.eval(`[...document.querySelectorAll('button')].find(x => /place my own points/i.test(x.innerText)).click()`)
await b.sleep(400)
await b.eval(`document.querySelector('.map').scrollIntoView({block:'start'})`)
await b.sleep(400)
const rect = await b.eval(`(() => { const r = document.querySelector('.map svg').getBoundingClientRect(); return [r.left, r.top, r.width, r.height] })()`)
const W = 1536, toScreen = (p) => [rect[0] + p[0] / W * rect[2], rect[1] + p[1] / W * rect[3]]
const dp = depot ? [depot[0], depot[1]] : picked[0]
await b.click(...toScreen(dp)); await b.sleep(250)
for (const p of picked) { if (dist(p, dp) < 30) continue; await b.click(...toScreen(p)); await b.sleep(120) }
await b.eval(`[...document.querySelectorAll('button')].find(x => /plan route|replan/i.test(x.innerText)).click()`)
const t0 = Date.now(); let done = false
while (Date.now() - t0 < 120000 && !done) { await b.sleep(700); done = await b.eval(`/verified|cannot|violation|unresolved/i.test(document.querySelector('.result')?.innerText ?? '') && !!document.querySelector('.drive')`) }
await b.eval('window.scrollTo(0,0)'); await b.sleep(900)
await b.shot(out)
console.log(await b.eval(`document.querySelector('.result')?.innerText.replace(/\\n/g,' | ')`))
await b.close()
