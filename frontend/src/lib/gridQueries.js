import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

export const gridKeys = {
	status: ['grid', 'status'],
}

/** Grid has no clock of its own to poll externally -- see distributorQueries for why
 *  this polls at 1s rather than the slower 5s tick cadence. */
export function useGridStatus() {
	return useQuery({
		queryKey: gridKeys.status,
		queryFn: () => request('/api/grid/status/'),
		refetchInterval: 1000,
		retry: false,
	})
}

/** Manually sets the deviation every subsequent tick carries, bounded to +-0.25 Hz
 *  server-side, and always switches automatic control off. Not wired to a control
 *  anywhere yet, but the backend already supports it. */
export function useSetFrequencyDeviation(onSuccess) {
	const qc = useQueryClient()
	return useMutation({
		mutationFn: (frequencyDeviation) =>
			request('/api/grid/frequency-deviation/', { method: 'PUT', data: { frequencyDeviation } }),
		onSuccess: (...args) => {
			qc.invalidateQueries({ queryKey: gridKeys.status })
			onSuccess?.(...args)
		},
	})
}
