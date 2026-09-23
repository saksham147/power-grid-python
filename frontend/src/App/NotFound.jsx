import { Link } from 'react-router-dom'

export default function NotFound() {
	return (
		<div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-950 text-zinc-100">
			<h1 className="text-2xl font-bold">Page not found</h1>
			<Link to="/" className="text-cyan-400 underline">
				back to home
			</Link>
		</div>
	)
}
