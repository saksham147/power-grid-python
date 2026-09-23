import { PLANT_TYPES, PROFILE_TYPES, OFFLINE } from './constants'

// Flat two-tone icons on a shared 48x48 canvas -- one main color per icon (the
// plant's or building profile's own color from constants.js) with black/white
// overlays for shading and windows, so the whole set stays consistent without
// carrying any image assets. Purely presentational: no state, no data.

const SHADE = { fill: '#000', fillOpacity: 0.2 }
const LIGHT = { fill: '#fff', fillOpacity: 0.92 }

function Svg({ size, children }) {
	return (
		<svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" className="shrink-0">
			{children}
		</svg>
	)
}

function HouseIcon({ c, size }) {
	return (
		<Svg size={size}>
			<rect x="11" y="22" width="26" height="18" rx="2" fill={c} />
			<polygon points="6,25 24,8 42,25" fill={c} />
			<polygon points="6,25 24,8 42,25" {...SHADE} />
			<rect x="20" y="29" width="8" height="11" rx="1" {...LIGHT} />
			<rect x="14" y="26" width="5" height="5" rx="1" {...LIGHT} />
			<rect x="29" y="26" width="5" height="5" rx="1" {...LIGHT} />
		</Svg>
	)
}

function ShopIcon({ c, size }) {
	return (
		<Svg size={size}>
			<rect x="9" y="17" width="30" height="23" rx="2" fill={c} />
			<rect x="6" y="11" width="36" height="8" rx="2" fill={c} />
			<rect x="6" y="11" width="36" height="8" rx="2" {...SHADE} />
			<rect x="10" y="11" width="4" height="8" {...LIGHT} />
			<rect x="20" y="11" width="4" height="8" {...LIGHT} />
			<rect x="30" y="11" width="4" height="8" {...LIGHT} />
			<rect x="12" y="24" width="10" height="9" rx="1" {...LIGHT} />
			<rect x="27" y="24" width="9" height="16" rx="1" {...LIGHT} />
		</Svg>
	)
}

function FactoryIcon({ c, size }) {
	return (
		<Svg size={size}>
			<rect x="31" y="9" width="7" height="20" rx="1" fill={c} />
			<rect x="31" y="9" width="7" height="20" rx="1" {...SHADE} />
			<circle cx="35" cy="6" r="3.5" {...LIGHT} fillOpacity="0.6" />
			<polygon points="6,40 6,22 16,29 16,22 26,29 26,22 36,29 36,40" fill={c} />
			<rect x="6" y="29" width="34" height="11" fill={c} />
			<rect x="10" y="32" width="5" height="5" rx="1" {...LIGHT} />
			<rect x="20" y="32" width="5" height="5" rx="1" {...LIGHT} />
			<rect x="30" y="32" width="5" height="5" rx="1" {...LIGHT} />
		</Svg>
	)
}

function GovIcon({ c, size }) {
	return (
		<Svg size={size}>
			<polygon points="5,19 24,6 43,19" fill={c} />
			<polygon points="5,19 24,6 43,19" {...SHADE} />
			<circle cx="24" cy="14" r="2.5" {...LIGHT} />
			<rect x="9" y="21" width="5" height="15" rx="1" fill={c} />
			<rect x="18" y="21" width="5" height="15" rx="1" fill={c} />
			<rect x="25" y="21" width="5" height="15" rx="1" fill={c} />
			<rect x="34" y="21" width="5" height="15" rx="1" fill={c} />
			<rect x="6" y="36" width="36" height="5" rx="1" fill={c} />
			<rect x="6" y="36" width="36" height="5" rx="1" {...SHADE} />
		</Svg>
	)
}

const BUILDING_ICONS = { RESIDENTIAL: HouseIcon, COMMERCIAL: ShopIcon, INDUSTRIAL: FactoryIcon, GOV: GovIcon }

/** A house, shop, factory or government building, colored by its profile. */
export function BuildingIcon({ type, size = 32 }) {
	const Icon = BUILDING_ICONS[type] ?? HouseIcon
	return <Icon c={PROFILE_TYPES[type]?.color ?? OFFLINE} size={size} />
}

function ThermalIcon({ c, size }) {
	return (
		<Svg size={size}>
			<path d="M9 40 L14 16 H30 L35 40 Z" fill={c} />
			<path d="M9 40 L14 16 H22 L20 40 Z" {...SHADE} />
			<rect x="35" y="14" width="6" height="26" rx="1" fill={c} />
			<rect x="35" y="14" width="6" height="26" rx="1" {...SHADE} />
			<circle cx="22" cy="10" r="4" {...LIGHT} fillOpacity="0.65" />
			<circle cx="29" cy="6" r="3" {...LIGHT} fillOpacity="0.45" />
			<circle cx="38" cy="8" r="3" {...LIGHT} fillOpacity="0.55" />
			<rect x="6" y="40" width="38" height="3" rx="1" {...SHADE} fillOpacity="0.3" />
		</Svg>
	)
}

function SolarIcon({ c, size }) {
	return (
		<Svg size={size}>
			<circle cx="37" cy="11" r="6" fill="#a5f3fc" />
			<polygon points="6,36 14,18 42,18 34,36" fill={c} />
			<polygon points="6,36 14,18 42,18 34,36" {...SHADE} />
			<g stroke="#fff" strokeOpacity="0.85" strokeWidth="1.4">
				<line x1="10" y1="27" x2="38" y2="27" />
				<line x1="22" y1="18" x2="18" y2="36" />
				<line x1="30" y1="18" x2="26" y2="36" />
			</g>
			<rect x="21" y="36" width="4" height="6" fill={c} />
			<rect x="14" y="41" width="18" height="3" rx="1" fill={c} />
		</Svg>
	)
}

/** The blades only spin for a plant that is actually generating. */
function WindIcon({ c, size, spinning }) {
	return (
		<Svg size={size}>
			<polygon points="22.5,22 25.5,22 27,43 21,43" fill={c} />
			<polygon points="22.5,22 25.5,22 27,43 21,43" {...SHADE} />
			<g
				className={spinning ? 'motion-safe:animate-[spin_3s_linear_infinite]' : undefined}
				style={{ transformBox: 'fill-box', transformOrigin: '50% 50%' }}
			>
				<path d="M24 20 L21.5 4 Q24 2 26.5 4 Z" fill={c} />
				<path d="M24 20 L38.5 28 Q38 31 35 31 Z" fill={c} />
				<path d="M24 20 L9.5 28 Q10 31 13 31 Z" fill={c} />
				<circle cx="24" cy="20" r="3.2" {...LIGHT} />
			</g>
		</Svg>
	)
}

/** A generating unit. `spinning` only matters for wind (the blades).
 *
 * Storage icons (battery/hydrogen) aren't ported yet -- no storage-unit feature
 * exists in this port's backend, see TASKS.md.
 */
export function SourceIcon({ type, size = 40, spinning = false }) {
	const c = PLANT_TYPES[type]?.color ?? OFFLINE
	if (type === 'SOLAR') return <SolarIcon c={c} size={size} />
	if (type === 'WIND') return <WindIcon c={c} size={size} spinning={spinning} />
	return <ThermalIcon c={c} size={size} />
}

/** The Grid hub: a transmission pylon. */
export function GridIcon({ color, size = 44 }) {
	return (
		<Svg size={size}>
			<g stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" fill="none">
				<path d="M24 5 L15 43 M24 5 L33 43" />
				<path d="M19 24 H29 M16.5 34 H31.5" />
				<path d="M19 24 L31.5 34 M29 24 L16.5 34" />
				<path d="M9 13 H39" />
				<path d="M13 13 L24 5 L35 13" />
			</g>
			<circle cx="9" cy="16" r="1.8" fill={color} />
			<circle cx="39" cy="16" r="1.8" fill={color} />
		</Svg>
	)
}

/** A landscape plot marker for a zone -- a small block of buildings. */
export function ZoneIcon({ color = '#22d3ee', size = 20 }) {
	return (
		<Svg size={size}>
			<rect x="5" y="20" width="12" height="20" rx="1.5" fill={color} />
			<rect x="19" y="10" width="12" height="30" rx="1.5" fill={color} />
			<rect x="19" y="10" width="12" height="30" rx="1.5" {...SHADE} />
			<rect x="33" y="24" width="10" height="16" rx="1.5" fill={color} />
		</Svg>
	)
}
