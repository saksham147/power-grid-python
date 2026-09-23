import { useCallback, useMemo, useState } from 'react'

import { useDemand, useUnits, useZones } from '../lib/customerQueries.js'
import { useZoneCapacities } from '../lib/distributorQueries.js'
import { useGridStatus } from '../lib/gridQueries.js'
import { usePlants } from '../lib/producerQueries.js'
import GridMap from './GridMap.jsx'

const GRID_SELECTION = { kind: 'grid' }

/**
 * The whole app, one page: a live simulator-style map (plants and zones feeding a
 * Grid hub) instead of a stats-and-tables dashboard. Owns every query and the
 * derived joins between them, plus which thing on the map is currently selected.
 */
export default function Dashboard() {
	const [selection, setSelection] = useState(GRID_SELECTION)
	const select = useCallback(
		(kind, id) => setSelection(kind === 'grid' ? GRID_SELECTION : { kind, id }),
		[],
	)

	const { data: grid, isError: gridErrored } = useGridStatus()
	const { data: rawPlants, isError: plantsErrored } = usePlants()
	const { data: rawZones, isError: zonesErrored } = useZones()
	const { data: rawUnits, isError: unitsErrored } = useUnits()
	const { data: demand } = useDemand()
	const { data: zoneCapacities } = useZoneCapacities()

	const gridOnline = Boolean(grid) && !gridErrored
	const plantsOnline = Boolean(rawPlants) && !plantsErrored
	const customerOnline = Boolean(rawZones) && !zonesErrored && Boolean(rawUnits) && !unitsErrored

	// Sorted once here so a poll can never reshuffle a tile the player just learned
	// the position of -- the services list these in no guaranteed order.
	const plants = useMemo(() => rawPlants && [...rawPlants].sort((a, b) => a.id - b.id), [rawPlants])
	const zones = useMemo(
		() => rawZones && [...rawZones].sort((a, b) => a.zoneId.localeCompare(b.zoneId)),
		[rawZones],
	)

	// Joined by zone id so a zone's plot has its buildings, live demand and capacity
	// status without any of the three queries knowing about the others.
	const unitsByZone = useMemo(() => {
		const map = new Map()
		for (const u of rawUnits ?? []) {
			if (!map.has(u.zoneId)) map.set(u.zoneId, [])
			map.get(u.zoneId).push(u)
		}
		return map
	}, [rawUnits])
	const demandByZone = useMemo(() => new Map((demand?.zones ?? []).map((z) => [z.zoneId, z])), [demand])
	const capacityByZone = useMemo(
		() => new Map((zoneCapacities ?? []).map((c) => [c.zoneId, c])),
		[zoneCapacities],
	)

	return (
		<div className="flex h-screen w-screen flex-col overflow-hidden bg-zinc-950 text-zinc-100">
			<header className="flex items-center justify-between border-b border-zinc-800 px-4 py-3 sm:px-6">
				<h1 className="text-sm font-semibold tracking-tight">Power Grid</h1>
				<span className="tabular-nums text-xs text-zinc-400">
					{grid?.simulatedTime ?? '--:--'} <span className="text-zinc-600">· tick {grid?.tickNumber ?? 0}</span>
				</span>
			</header>

			<GridMap
				grid={grid}
				gridOnline={gridOnline}
				plants={plantsOnline ? plants : null}
				zones={customerOnline ? zones : null}
				unitsByZone={unitsByZone}
				demandByZone={demandByZone}
				capacityByZone={capacityByZone}
				selection={selection}
				onSelect={select}
				onAddPlant={() => {}}
				onAddZone={() => {}}
				onAddUnit={() => {}}
			/>

			{/* Placeholder until the detail-panel task lands and replaces this with the
			    real bottom panel -- proves selection is wired without building the
			    view that will actually own it. */}
			<p className="border-t border-zinc-800 bg-zinc-900 px-4 py-2 text-xs text-zinc-500">
				Selected: {selection.kind}
				{selection.id ? ` (${selection.id})` : ''} — detail panel not built yet.
			</p>
		</div>
	)
}
