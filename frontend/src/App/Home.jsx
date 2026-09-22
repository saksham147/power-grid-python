import { Link } from 'react-router-dom'
import { useGridStatus } from '../lib/gridQueries.js'
import { useCounterStore } from '../store/useCounterStore.js'

export default function Home() {
	const count = useCounterStore((state) => state.count)
	const increment = useCounterStore((state) => state.increment)
	const { data: status, isLoading, isError } = useGridStatus()

	return (
		<div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-900 text-slate-100">
			<h1 className="text-3xl font-bold">Power Grid</h1>
			<button
				type="button"
				onClick={increment}
				className="rounded-md bg-blue-600 px-4 py-2 font-medium hover:bg-blue-500"
			>
				count is {count}
			</button>
			<p className="text-sm text-slate-400">
				{isLoading && 'loading grid status...'}
				{isError && 'grid status unavailable (is the django server running?)'}
				{status && `tick ${status.tickNumber}, day ${status.simulatedDay}, ${status.simulatedTime}`}
			</p>
			<Link to="/does-not-exist" className="text-blue-400 underline">
				see the not-found page
			</Link>
		</div>
	)
}
