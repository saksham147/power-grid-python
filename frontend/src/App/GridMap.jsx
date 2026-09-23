import { memo } from 'react'

import { kw, mw } from '../lib/format'
import { ACCENT, OFFLINE, NEGATIVE, POSITIVE, PLANT_TYPES, PROFILE_TYPES } from './constants'
import { BuildingIcon, SourceIcon, GridIcon, ZoneIcon } from './icons'

// The map: plain DOM tiles in a CSS flex/grid layout -- no canvas, no per-node
// measurement, no graph library. Tiles are memoized on their own data object, so a
// poll that changes one plant re-renders that tile, not the whole map -- the same
// reasoning the reference's own game/World.jsx documents for why it replaced a
// React Flow canvas with exactly this.
//
// Storage isn't rendered here: no storage-unit feature exists in this port's
// backend yet, see TASKS.md. Per-tile revenue isn't shown either: it depends on
// Billing's money-flow feature, also not in this port yet.
//
// A soft red is the only color here that isn't a shade of the single accent hue --
// reserved for a genuine near-capacity/over-capacity warning, where dropping color
// differentiation would actually cost something. See App/constants.js.

const WARNING = '#fca5a5'

const tileBase =
	'relative flex flex-col items-center rounded-xl border bg-zinc-900 text-center shadow-sm transition '
	+ 'hover:-translate-y-0.5 hover:border-zinc-600 focus-visible:outline-2 focus-visible:outline-cyan-400'

const selectedRing = 'border-cyan-400 ring-2 ring-cyan-400/40'

function Meter({ pct, color }) {
	return (
		<div className="h-1 w-full overflow-hidden rounded-full bg-zinc-800">
			<div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} />
		</div>
	)
}

/** A power plant: icon, name, and a meter of output against rating. */
const PlantTile = memo(function PlantTile({ plant, selected, onSelect }) {
	const meta = PLANT_TYPES[plant.type] ?? { color: OFFLINE, label: plant.type }
	const pct = plant.capacityMw > 0 ? (plant.currentOutputMw / plant.capacityMw) * 100 : 0
	const spinning = plant.active && plant.currentOutputMw > 0

	return (
		<button
			type="button"
			title={`${plant.name} · ${meta.label}`}
			onClick={(e) => { e.stopPropagation(); onSelect('plant', plant.id) }}
			className={`${tileBase} w-[84px] gap-0.5 px-1.5 pb-1.5 pt-2 ${selected ? selectedRing : 'border-zinc-800'} ${plant.active ? '' : 'opacity-60 grayscale'}`}
		>
			<SourceIcon type={plant.type} size={40} spinning={spinning} />
			<span className="w-full truncate text-[10px] font-semibold text-zinc-100">{plant.name}</span>
			<span className="text-[9px] tabular-nums text-zinc-400">{plant.active ? mw(plant.currentOutputMw) : 'off'}</span>
			<Meter pct={pct} color={plant.active ? meta.color : OFFLINE} />
		</button>
	)
})

/** One house, shop, factory or government building inside a zone. The meter is its
 *  live load against its own rating, turning warning-red near the ceiling and full
 *  red past it. */
const BuildingTile = memo(function BuildingTile({ unit, selected, onSelect }) {
	const meta = PROFILE_TYPES[unit.type] ?? { color: OFFLINE, label: unit.type }
	const pct = unit.capacityKw > 0 ? (unit.demandKw / unit.capacityKw) * 100 : 0
	const meterColor = pct >= 100 ? NEGATIVE : pct >= 85 ? WARNING : meta.color

	return (
		<button
			type="button"
			title={`${unit.name} · ${meta.label} · ${kw(unit.demandKw)}`}
			onClick={(e) => { e.stopPropagation(); onSelect('unit', unit.unitId) }}
			className={`${tileBase} w-[52px] gap-0.5 px-1 pb-1 pt-1.5 ${selected ? selectedRing : 'border-zinc-800'}`}
		>
			<BuildingIcon type={unit.type} size={30} />
			<Meter pct={pct} color={meterColor} />
		</button>
	)
})

function AddTile({ label, onClick, compact }) {
	return (
		<button
			type="button"
			onClick={(e) => { e.stopPropagation(); onClick() }}
			className={`flex flex-col items-center justify-center gap-0.5 rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 text-zinc-500 transition hover:border-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 ${compact ? 'h-[46px] w-[52px]' : 'h-[88px] w-[84px]'}`}
		>
			<span className="text-lg leading-none">+</span>
			<span className="text-[9px] font-medium">{label}</span>
		</button>
	)
}

function Offline({ label }) {
	return (
		<p className="rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 px-3 py-4 text-center text-xs text-zinc-500">
			{label} offline
		</p>
	)
}

function ZonePlot({ zone, units, demandKw, overCapacity, selection, onSelect, onAddUnit }) {
	const selected = selection.kind === 'zone' && selection.id === zone.zoneId

	return (
		<section
			className={`rounded-2xl border-2 p-2.5 transition ${selected ? 'border-cyan-400 bg-cyan-950/20' : overCapacity ? 'border-red-500/50 bg-zinc-900' : 'border-zinc-800 bg-zinc-900/60'}`}
		>
			<button
				type="button"
				onClick={(e) => { e.stopPropagation(); onSelect('zone', zone.zoneId) }}
				className="flex w-full items-center gap-2 rounded-lg text-left focus-visible:outline-2 focus-visible:outline-cyan-400"
			>
				<ZoneIcon color={ACCENT} size={20} />
				<span className="truncate text-xs font-semibold text-zinc-100">{zone.name}</span>
				{overCapacity && (
					<span className="rounded-full bg-red-950 px-1.5 py-0.5 text-[9px] font-semibold text-red-400">OVER</span>
				)}
				<span className="ml-auto shrink-0 text-right text-[9px] tabular-nums text-zinc-400">{kw(demandKw)}</span>
			</button>

			<div className="mt-2 flex flex-wrap gap-1.5">
				{units.map((u) => (
					<BuildingTile
						key={u.unitId}
						unit={u}
						selected={selection.kind === 'unit' && selection.id === u.unitId}
						onSelect={onSelect}
					/>
				))}
				<AddTile compact label="Add" onClick={() => onAddUnit(zone.zoneId)} />
			</div>
		</section>
	)
}

function GridHub({ grid, online, selected, onSelect }) {
	const overloaded = Boolean(grid?.loadExceeded)
	// loadExceeded only says demand beat supply; the opposite -- supply far above
	// demand -- is not "balanced" either, so say what it is.
	const surplus = !overloaded && (grid?.frequencyDeviationHz ?? 0) > 0.05
	const color = !online ? OFFLINE : overloaded ? NEGATIVE : ACCENT

	return (
		<button
			type="button"
			onClick={(e) => { e.stopPropagation(); onSelect('grid') }}
			className={`${tileBase} w-32 shrink-0 self-center gap-0.5 rounded-2xl border-2 px-3 py-3 ${selected ? selectedRing : 'border-zinc-800'}`}
		>
			<GridIcon color={color} size={48} />
			<span className="text-sm font-semibold text-zinc-100">Grid</span>
			<span
				className="mt-1 rounded-full px-2 py-0.5 text-[9px] font-semibold"
				style={{
					background: !online ? '#27272a' : overloaded ? '#450a0a' : surplus ? '#164e63' : '#083344',
					color: !online ? '#71717a' : overloaded ? NEGATIVE : surplus ? POSITIVE : ACCENT,
				}}
			>
				{!online ? 'OFFLINE' : overloaded ? 'OVERLOADED' : surplus ? 'SURPLUS' : 'BALANCED'}
			</span>
		</button>
	)
}

/** A short conduit between two regions. Animated only while power is actually
 *  flowing -- the CSS for that lives in index.css and switches itself off under
 *  prefers-reduced-motion. */
function PowerLine({ live }) {
	return (
		<div
			aria-hidden="true"
			className={`power-line h-7 w-1 shrink-0 self-center lg:h-1 lg:w-9 ${live ? 'power-line-live' : ''}`}
		/>
	)
}

function Region({ title, className = '', children }) {
	return (
		<section className={`min-w-0 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-3 ${className}`}>
			<h2 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{title}</h2>
			{children}
		</section>
	)
}

export default function GridMap({
	grid, gridOnline, plants, zones, unitsByZone, demandByZone, capacityByZone,
	selection, onSelect, onAddPlant, onAddZone, onAddUnit,
}) {
	return (
		<main
			onClick={() => onSelect('grid')}
			className="min-h-0 flex-1 overflow-auto bg-zinc-950 [background-image:radial-gradient(#27272a_1px,transparent_1px)] [background-size:20px_20px]"
		>
			<div className="flex min-h-full flex-col items-stretch p-3 sm:p-4 lg:flex-row">
				<Region title="Generation" className="lg:flex-1">
					<p className="mb-1.5 text-[11px] font-medium text-zinc-400">Power plants</p>
					{plants ? (
						<div className="flex flex-wrap gap-2">
							{plants.map((p) => (
								<PlantTile
									key={p.id}
									plant={p}
									selected={selection.kind === 'plant' && selection.id === p.id}
									onSelect={onSelect}
								/>
							))}
							<AddTile label="Plant" onClick={onAddPlant} />
						</div>
					) : (
						<Offline label="Producer" />
					)}
				</Region>

				<PowerLine live={gridOnline && Boolean(plants?.some((p) => p.active))} />
				<GridHub grid={grid} online={gridOnline} selected={selection.kind === 'grid'} onSelect={onSelect} />
				<PowerLine live={gridOnline && Boolean(zones?.length)} />

				<Region title="City" className="lg:flex-[1.7]">
					{zones ? (
						<div className="grid grid-cols-1 gap-3 md:grid-cols-2">
							{zones.map((z) => (
								<ZonePlot
									key={z.zoneId}
									zone={z}
									units={unitsByZone.get(z.zoneId) ?? []}
									demandKw={demandByZone.get(z.zoneId)?.demandKw ?? 0}
									overCapacity={Boolean(capacityByZone.get(z.zoneId)?.overCapacity)}
									selection={selection}
									onSelect={onSelect}
									onAddUnit={onAddUnit}
								/>
							))}
							<button
								type="button"
								onClick={(e) => { e.stopPropagation(); onAddZone() }}
								className="flex min-h-[88px] items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-zinc-700 bg-zinc-900/40 text-xs font-medium text-zinc-500 transition hover:border-zinc-500 hover:text-zinc-300"
							>
								<span className="text-lg leading-none">+</span> Add zone
							</button>
						</div>
					) : (
						<Offline label="Customer" />
					)}
				</Region>
			</div>
		</main>
	)
}
