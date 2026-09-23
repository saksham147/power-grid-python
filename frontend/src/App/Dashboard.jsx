import { useCallback, useMemo, useState } from 'react'

import { useDemand, useUnits, useZones } from '../lib/customerQueries.js'
import { useZoneCapacities } from '../lib/distributorQueries.js'
import { useGridStatus } from '../lib/gridQueries.js'
import { useDeletePlant, usePlants } from '../lib/producerQueries.js'
import GridMap from './GridMap.jsx'
import {
	AddCustomerModal, AddPlantModal, AddZoneModal, EditCustomerModal, EditPlantModal, EditZoneModal,
	ManageZoneCapacitiesModal,
} from './modals.jsx'

const GRID_SELECTION = { kind: 'grid' }

const btn = 'rounded-lg border px-3 py-1.5 text-xs font-medium transition'
const btnPlain = `${btn} border-zinc-700 text-zinc-300 hover:bg-zinc-800`

/** The bottom bar: nothing selected (or the grid tile) shows the "manage
 *  capacities" affordance; a plant/zone/building shows its name and an Edit button.
 *  A selection that no longer exists (just deleted) simply falls back to showing
 *  nothing extra, the same graceful "look it up live" pattern used everywhere else
 *  in this project. */
function SelectionBar({ selection, plants, zones, unitsByZone, onEditPlant, onEditZone, onEditUnit, onManageCapacities }) {
	if (selection.kind === 'plant') {
		const plant = plants?.find((p) => p.id === selection.id)
		if (!plant) return null
		return (
			<div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900 px-4 py-2">
				<span className="text-xs text-zinc-400">Plant: <span className="text-zinc-100">{plant.name}</span></span>
				<button type="button" onClick={() => onEditPlant(plant)} className={btnPlain}>Edit</button>
			</div>
		)
	}
	if (selection.kind === 'zone') {
		const zone = zones?.find((z) => z.zoneId === selection.id)
		if (!zone) return null
		return (
			<div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900 px-4 py-2">
				<span className="text-xs text-zinc-400">Zone: <span className="text-zinc-100">{zone.name}</span></span>
				<button type="button" onClick={() => onEditZone(zone)} className={btnPlain}>Edit</button>
			</div>
		)
	}
	if (selection.kind === 'unit') {
		for (const units of unitsByZone.values()) {
			const unit = units.find((u) => u.unitId === selection.id)
			if (unit) {
				return (
					<div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900 px-4 py-2">
						<span className="text-xs text-zinc-400">Building: <span className="text-zinc-100">{unit.name}</span></span>
						<button type="button" onClick={() => onEditUnit(unit)} className={btnPlain}>Edit</button>
					</div>
				)
			}
		}
		return null
	}
	return (
		<div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900 px-4 py-2">
			<span className="text-xs text-zinc-500">Grid selected</span>
			<button type="button" onClick={onManageCapacities} className={btnPlain}>Zone capacities</button>
		</div>
	)
}

/**
 * The whole app, one page: a live simulator-style map (plants and zones feeding a
 * Grid hub) instead of a stats-and-tables dashboard. Owns every query, the derived
 * joins between them, which thing on the map is selected, and every modal.
 */
export default function Dashboard() {
	const [selection, setSelection] = useState(GRID_SELECTION)
	const select = useCallback(
		(kind, id) => setSelection(kind === 'grid' ? GRID_SELECTION : { kind, id }),
		[],
	)
	const backToGrid = useCallback(() => setSelection(GRID_SELECTION), [])

	const [showAddPlant, setShowAddPlant] = useState(false)
	const [showAddZone, setShowAddZone] = useState(false)
	// null = closed; { zoneId } = open, with that zone preselected (undefined = no preselection).
	const [addingUnit, setAddingUnit] = useState(null)
	const [editingPlant, setEditingPlant] = useState(null)
	const [editingZone, setEditingZone] = useState(null)
	const [editingUnit, setEditingUnit] = useState(null)
	const [managingCapacities, setManagingCapacities] = useState(false)

	const deletePlant = useDeletePlant()

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

	// A plant decommission credits Billing (inside EditPlantModal) before this runs
	// -- the same two-step ordering a purchase uses in reverse (pay Billing, then
	// create in Producer). A failed refund never reaches this callback. Closes the
	// modal itself too: onDeleted firing is not the same event as onClose, and nothing
	// else here would dismiss a modal now showing a plant that no longer exists.
	const handlePlantDecommissioned = useCallback((plantId) => {
		setEditingPlant(null)
		backToGrid()
		deletePlant.mutate(plantId)
	}, [backToGrid, deletePlant])

	const handleZoneDeleted = useCallback(() => {
		setEditingZone(null)
		backToGrid()
	}, [backToGrid])

	const handleUnitDeleted = useCallback(() => {
		setEditingUnit(null)
		backToGrid()
	}, [backToGrid])

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
				onAddPlant={() => setShowAddPlant(true)}
				onAddZone={() => setShowAddZone(true)}
				onAddUnit={(zoneId) => setAddingUnit({ zoneId })}
			/>

			<SelectionBar
				selection={selection}
				plants={plants}
				zones={zones}
				unitsByZone={unitsByZone}
				onEditPlant={setEditingPlant}
				onEditZone={setEditingZone}
				onEditUnit={setEditingUnit}
				onManageCapacities={() => setManagingCapacities(true)}
			/>

			{showAddPlant && <AddPlantModal onClose={() => setShowAddPlant(false)} />}
			{editingPlant && (
				<EditPlantModal plant={editingPlant} onClose={() => setEditingPlant(null)} onDeleted={handlePlantDecommissioned} />
			)}
			{showAddZone && <AddZoneModal onClose={() => setShowAddZone(false)} />}
			{editingZone && <EditZoneModal zone={editingZone} onClose={() => setEditingZone(null)} onDeleted={handleZoneDeleted} />}
			{addingUnit && (
				<AddCustomerModal zones={zones ?? []} defaultZoneId={addingUnit.zoneId} onClose={() => setAddingUnit(null)} />
			)}
			{editingUnit && (
				<EditCustomerModal unit={editingUnit} onClose={() => setEditingUnit(null)} onDeleted={handleUnitDeleted} />
			)}
			{managingCapacities && (
				<ManageZoneCapacitiesModal
					capacities={zoneCapacities ?? []}
					zones={zones ?? []}
					onClose={() => setManagingCapacities(false)}
				/>
			)}
		</div>
	)
}
