// The access code that unlocks live mode on a shared deployment (the server decides; this only remembers what was typed).
const KEY = 'orbitroute-access-code'

export function getCode(): string {
  try { return localStorage.getItem(KEY) ?? '' } catch { return '' }
}

export function setCode(code: string) {
  try { if (code) localStorage.setItem(KEY, code); else localStorage.removeItem(KEY) } catch { /* private window: the code is just not remembered */ }
}

/** The code in a link like https://host/#code=abc. The part after # never reaches the server, its logs or a Referer header. */
export function codeFromHash(hash: string): string {
  const value = new URLSearchParams(hash.replace(/^#/, '')).get('code')
  return value ? value.trim() : ''
}

/** Remember the code carried by the link and take it out of the address bar, so it is not copied on by accident. */
export function adoptCodeFromLink(): void {
  const code = codeFromHash(window.location.hash)
  if (!code) return
  setCode(code)
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}

export function accessHeaders(): Record<string, string> {
  const code = getCode()
  return code ? { 'X-Access-Code': code } : {}
}

export type Access = { required: boolean; live: boolean; window_open: boolean; message: string }

export async function fetchAccess(): Promise<Access | null> {
  try {
    const r = await fetch('/api/access', { headers: accessHeaders() })
    if (r.status === 429) {
      const j = await r.json().catch(() => ({}))
      return { required: true, live: false, window_open: true, message: typeof j.detail === 'string' ? j.detail : 'Too many wrong codes. Try again later.' }
    }
    return r.ok ? ((await r.json()) as Access) : null
  } catch { return null }
}
