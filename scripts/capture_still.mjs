// Screenshot of a finished one-click run of one sample, for the README. Needs the app on http://localhost:8000.
// Usage: node scripts/capture_still.mjs SAMPLE OUT.png [LANG]   (for example: houston-harvey-b docs/flood-cutoff.png ru)
import { launch } from './cdp.mjs'

const [sample, out, lang] = process.argv.slice(2)
const b = await launch(1440, 1200)
await b.goto('http://localhost:8000/')
if (lang) { await b.eval(`localStorage.setItem('orbitroute-lang', '${lang}')`); await b.goto('http://localhost:8000/') } // the interface language
await b.sleep(1200)
await b.eval(`(() => { const s = document.querySelector('.request select'); s.value = '${sample}'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`)
await b.sleep(800)
await b.eval(`[...document.querySelectorAll('button')].find(x => /try it with|попробовать/i.test(x.innerText)).click()`)
const t0 = Date.now()
let done = false
while (Date.now() - t0 < 90000 && !done) {
  await b.sleep(500)
  done = await b.eval(`/verified|cannot|violation|проверено|нельзя|нарушен/i.test(document.querySelector('.result')?.innerText ?? '') && !!document.querySelector('.drive')`)
}
await b.eval('window.scrollTo(0, 0)')
await b.sleep(900)
await b.shot(out)
console.log(await b.eval(`document.querySelector('.result')?.innerText.replace(/\\n/g, ' | ')`))
await b.close()
