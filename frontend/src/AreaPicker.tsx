import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import type { Sample } from './types'
import { accessHeaders } from './access'
import { t } from './i18n'

const SPAN_M = 1500 // must match the server: the picked square is 1.5 km on a side
const MIN_ZOOM = 14
const PRESETS: [string, number, number][] = [
  ['Columbus, OH', 39.95, -83.1],
  ['Atlanta, GA', 33.75, -84.39],
  ['Chicago, IL', 41.85, -87.65],
  ['Dallas, TX', 32.78, -96.8],
  ['Phoenix, AZ', 33.45, -112.07],
  ['Seattle, WA', 47.6, -122.33],
  ['Denver, CO', 39.74, -104.99],
]

function squareBounds(lat: number, lng: number): L.LatLngBoundsExpression {
  const dLat = SPAN_M / 2 / 111320
  const dLng = SPAN_M / 2 / (111320 * Math.cos((lat * Math.PI) / 180))
  return [[lat - dLat, lng - dLng], [lat + dLat, lng + dLng]]
}

export default function AreaPicker(props: { onClose: () => void; onChosen: (s: Sample) => void }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const frame = useRef<L.Rectangle | null>(null)
  const [zoom, setZoom] = useState(15)
  const [busy, setBusy] = useState<string>('')
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { center: [39.95, -83.1], zoom: 15, minZoom: 4, maxZoom: 18, zoomControl: true })
    L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}', {
      maxNativeZoom: 16,
      maxZoom: 18,
      attribution: 'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map" target="_blank" rel="noreferrer">USGS The National Map</a>',
    }).addTo(m)
    const c = m.getCenter()
    frame.current = L.rectangle(squareBounds(c.lat, c.lng), { color: '#2dd4bf', weight: 2, fillColor: '#2dd4bf', fillOpacity: 0.12, interactive: false }).addTo(m)
    const sync = () => {
      const ctr = m.getCenter()
      frame.current?.setBounds(squareBounds(ctr.lat, ctr.lng) as L.LatLngBoundsLiteral)
      setZoom(m.getZoom())
    }
    m.on('move', sync)
    m.on('zoomend', sync)
    map.current = m
    return () => {
      m.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && props.onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [props])

  const go = (lat: number, lng: number) => {
    setError('')
    map.current?.setView([lat, lng], Math.max(map.current.getZoom(), 15))
  }

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setError('')
    setBusy('Searching…')
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?${new URLSearchParams({ format: 'json', limit: '1', countrycodes: 'us', q: query })}`)
      const j = (await r.json()) as { lat: string; lon: string }[]
      if (!j.length) setError(t('No place found in the United States. Try a city name or an address.'))
      else go(parseFloat(j[0].lat), parseFloat(j[0].lon))
    } catch {
      setError(t('Search is unavailable right now. Use the presets or pan the map.'))
    } finally {
      setBusy('')
    }
  }

  const choose = async () => {
    if (!map.current) return
    const { lat, lng } = map.current.getCenter()
    setError('')
    setBusy(t('Fetching the aerial image…'))
    try {
      const r = await fetch('/api/areas', { method: 'POST', headers: { 'Content-Type': 'application/json', ...accessHeaders() }, body: JSON.stringify({ lat, lon: lng }) })
      const j = await r.json()
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : t('This place could not be used.'))
      props.onChosen(j as Sample)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Something went wrong.'))
      setBusy('')
    }
  }

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={t('Choose an area')} onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal-card">
        <div className="modal-head">
          <div>
            <h2>{t('Choose an area')}</h2>
            <p>{t('Move the map so the square covers the streets you want to plan on. United States only (USGS aerial imagery).')}</p>
          </div>
          <button className="icon-btn" onClick={props.onClose} aria-label={t('Close')}>✕</button>
        </div>
        <form className="picker-search" onSubmit={search}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search a US city or address')} aria-label={t('Search a place')} />
          <button type="submit" className="chip" disabled={!!busy}>{t('Search')}</button>
        </form>
        <div className="presets">
          {PRESETS.map(([n, lat, lng]) => <button key={n} className="chip" onClick={() => go(lat, lng)}>{n}</button>)}
        </div>
        <div className="picker-map" ref={el} />
        <div className="modal-foot">
          <span className={error ? 'err' : 'muted'}>
            {error || busy || (zoom < MIN_ZOOM ? t('Zoom in until the square is small enough to see streets.') : t('1.5 km × 1.5 km square. Roads and buildings will be read from the imagery.'))}
          </span>
          <button className="primary inline" onClick={choose} disabled={!!busy || zoom < MIN_ZOOM}>{busy && busy ? t('Fetching…') : t('Use this area')}</button>
        </div>
        <p className="credit-line">{t('Search © OpenStreetMap contributors (Nominatim). Imagery: USGS NAIP, public domain.')}</p>
      </div>
    </div>
  )
}
