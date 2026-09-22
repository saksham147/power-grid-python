import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

export const producerKeys = {
	status: ['producer', 'status'],
	plants: ['producer', 'plants'],
	history: (id) => ['producer', 'plants', id, 'history'],
}

/** The clock advances every 5s; polling at 1s keeps it moving visibly without
 *  pretending to a resolution the tick does not have. */
export function useProducerStatus() {
	return useQuery({
		queryKey: producerKeys.status,
		queryFn: () => request('/api/producer/status/'),
		refetchInterval: 1000,
		retry: false,
	})
}

/** Output and energy are written back once per tick, so the fleet list tracks the tick. */
export function usePlants() {
	return useQuery({
		queryKey: producerKeys.plants,
		queryFn: () => request('/api/producer/plants/'),
		refetchInterval: 5000,
		retry: false,
	})
}

/** Fetched only while a plant's log panel is open -- the fleet view never needs it
 *  otherwise. New rows land once a tick, matching the fleet list's own cadence.
 *
 *  Forecast has no backend counterpart in this port (see producer.api.views's own
 *  docstring), so there is no usePlantForecast here the way the reference has one.
 */
export function usePlantHistory(id, enabled) {
	return useQuery({
		queryKey: producerKeys.history(id),
		queryFn: () => request(`/api/producer/plants/${id}/history/`, { params: { limit: 100 } }),
		enabled,
		refetchInterval: 5000,
		retry: false,
	})
}

function useRefreshingPlantMutation(mutationFn, onSuccess) {
	const qc = useQueryClient()
	return useMutation({
		mutationFn,
		onSuccess: (...args) => {
			qc.invalidateQueries({ queryKey: producerKeys.plants })
			onSuccess?.(...args)
		},
	})
}

export const useCreatePlant = (onSuccess) =>
	useRefreshingPlantMutation((body) => request('/api/producer/plants/', { method: 'POST', data: body }), onSuccess)

export const useUpgradePlant = (onSuccess) =>
	useRefreshingPlantMutation(
		({ id, ...body }) => request(`/api/producer/plants/${id}/`, { method: 'PUT', data: body }),
		onSuccess,
	)

/** Takes a plant in or out of service without touching its ratings -- see
 *  producer.api.views.plant_active. Not wired to a control anywhere yet, but the
 *  backend already supports it. */
export const useSetPlantActive = (onSuccess) =>
	useRefreshingPlantMutation(
		({ id, active }) => request(`/api/producer/plants/${id}/active/`, { method: 'PATCH', data: { active } }),
		onSuccess,
	)

export const useDeletePlant = (onSuccess) =>
	useRefreshingPlantMutation((id) => request(`/api/producer/plants/${id}/`, { method: 'DELETE' }), onSuccess)
