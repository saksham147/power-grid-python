import { Route, Routes } from 'react-router-dom'
import Home from './Home.jsx'
import NotFound from './NotFound.jsx'

export default function App() {
	return (
		<Routes>
			<Route path="/" element={<Home />} />
			<Route path="*" element={<NotFound />} />
		</Routes>
	)
}
