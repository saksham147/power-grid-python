import { Route, Routes } from 'react-router-dom'
import Dashboard from './Dashboard.jsx'
import NotFound from './NotFound.jsx'

export default function App() {
	return (
		<Routes>
			<Route path="/" element={<Dashboard />} />
			<Route path="*" element={<NotFound />} />
		</Routes>
	)
}
