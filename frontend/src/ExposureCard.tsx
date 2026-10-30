import { t } from './i18n'
import type { Exposure, XY } from './types'

const KIND_LABEL: Record<string, string> = {
  school: 'school', hospital_or_clinic: 'hospital or clinic', store_or_mall: 'store or mall', church_or_hall: 'church or hall',
  hotel_or_office: 'hotel or office', sports_or_event_hall: 'sports or event hall', apartment_block: 'apartment blocks', houses: 'houses', warehouse_or_factory: 'warehouse or factory',
  amenity: 'public building', hospital: 'hospital', clinic: 'clinic', community_centre: 'community centre', place_of_worship: 'place of worship', townhall: 'town hall',
  fire_station: 'fire station', college: 'college', university: 'university', library: 'library', mall: 'mall', supermarket: 'supermarket', department_store: 'department store',
}

// What the photo says about the water: how many buildings it touches and where a crowd could be put up. A rough reading, never a count.
export default function ExposureCard(props: { x: Exposure; running: boolean; onUseDepot: (xy: XY) => void }) {
  const { x } = props
  const label = (k: string) => t(KIND_LABEL[k] ?? k.replace(/_/g, ' '))
  return (
    <section className="panel exposure">
      <h2>{t('Water')} <small>{t('rough, from the photo')}</small></h2>
      <p className="expo-line">{t('{a} in the water, {b} surrounded by it (within 15 m), of {n} buildings found.', { a: x.in_water, b: x.surrounded, n: x.buildings })}</p>
      <p className="expo-line">
        {t('People')}: <b>{x.people_low}–{x.people_high}</b>{' '}
        <span className="muted">({t('2.5 people per building in or beside the water, houses only (commercial and industrial zones left out)')}). {t('The lower figure counts only buildings in the water, the upper adds the surrounded ones; the photo shows water, not its depth or any damage, and water under trees is missed, so both are rough.')}</span>
      </p>
      <h3>{t('Where a crowd could go')}</h3>
      {x.shelters.length === 0 ? (
        <p className="muted small">{t('No large dry building within reach by roads that are not under water.')}{x.cut_off_by_water ? ` ${t('{n} large dry buildings are cut off by the water.', { n: x.cut_off_by_water })}` : ''}</p>
      ) : (
        <ul className="shelters">
          {x.shelters.map((s, i) => {
            const what = s.name ?? (s.kind ? label(s.kind) : s.guess ? t('large dry building, type unknown (maybe {kind}, the model is not sure)', { kind: label(s.guess) }) : t('large dry building, type unknown'))
            return (
              <li key={i}>
                <span><b>{i + 1}.</b> {what}{s.name && s.kind ? ` (${label(s.kind)})` : ''} · {s.area_m2} m² · {t('up to ~{n} people on the ground floor', { n: s.capacity })} · {t('{m} min by dry roads from the depot', { m: s.minutes })}</span>
                <button type="button" disabled={props.running} onClick={() => props.onUseDepot(s.xy)}>{t('Use as depot')}</button>
              </li>
            )
          })}
        </ul>
      )}
      {Object.keys(x.not_shelters ?? {}).length > 0 && <p className="muted small">{t('Left out after looking at them:')} {Object.entries(x.not_shelters).map(([k, v]) => `${label(k)}: ${v}`).join(', ')}.</p>}
      <p className="muted small">{t('Nothing here says a building is open, safe or has the room: it says where to look first.')}</p>
    </section>
  )
}
