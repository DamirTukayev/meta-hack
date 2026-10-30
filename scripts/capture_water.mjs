// Screenshot of the flooded photo after a one-click run, tall enough to show the "Water" card (buildings in the water, possible shelters).
// Needs the app on http://localhost:8000. Usage: node scripts/capture_water.mjs SAMPLE OUT.png   (for example: houston-harvey-b docs/flood-water.png)
import { launch } from './cdp.mjs'

const [sample, out] = process.argv.slice(2)
const b = await launch(1440, 1500)
await b.goto('http://localhost:8000/')
await b.sleep(1200)
await b.eval(`(() => { const s = document.querySelector('select'); s.value = '${sample}'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`)
await b.sleep(800)
await b.eval(`[...document.querySelectorAll('button')].find(x => /try it with/i.test(x.innerText)).click()`)
const t0 = Date.now()
let done = false
while (Date.now() - t0 < 120000 && !done) {
  await b.sleep(700)
  done = await b.eval(`/verified|cannot|unresolved/i.test(document.querySelector('.result')?.innerText ?? '') && !!document.querySelector('.drive') && !!document.querySelector('.exposure')`)
}
await b.eval('window.scrollTo(0, 0)')
await b.sleep(900)
await b.shot(out)
console.log(await b.eval(`document.querySelector('.exposure')?.innerText.replace(/\\n/g, ' | ').slice(0, 300)`))
await b.close()
