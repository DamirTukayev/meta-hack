import { useState } from 'react'
import type { Access } from './access'

// Shown on a shared deployment while live mode is locked: the recorded demo works for everyone, the code opens the rest.
export default function AccessNote(props: { access: Access; onUnlock: (code: string) => Promise<void> }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [tried, setTried] = useState(false)
  const { access } = props
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim()) return
    setBusy(true)
    await props.onUnlock(code.trim())
    setBusy(false)
    setTried(true)
  }
  return (
    <div className="demo-note" role="note">
      <b>Recorded demo</b>{' '}
      {access.window_open
        ? 'The bundled images and their example sentences run on recorded model answers. Your own sentences, new map areas and voice are live and need the access code you were given.'
        : access.message}
      {access.required && access.window_open && (
        <form className="access-form" onSubmit={submit}>
          <input type="password" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Access code" aria-label="Access code" disabled={busy} />
          <button type="submit" disabled={busy || !code.trim()}>{busy ? 'Checking…' : 'Unlock'}</button>
          {tried && !access.live && <span className="err" role="alert">{access.message.startsWith('Too many') ? access.message : 'That code did not work.'}</span>}
        </form>
      )}
    </div>
  )
}
