import { useState, useEffect } from 'react'
import Home from './pages/Home.jsx'
import DocPage from './pages/DocPage.jsx'
import './styles/App.css'

// URL routing: hand-rolled, hash-based (no router library).
// Matches the convention used by web/leaderboard.
function parseHash() {
  const hash = window.location.hash.replace(/^#\/?/, '')
  if (hash.startsWith('docs/')) {
    return { type: 'doc', slug: hash.slice('docs/'.length) }
  }
  return { type: 'home' }
}

function App() {
  const [view, setView] = useState(parseHash())

  useEffect(() => {
    const onHashChange = () => setView(parseHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          <span className="brand-mark">ν</span>
          <span className="brand-name">Nomos</span>
        </a>
        <span className="brand-tagline">policy-grounded agent benchmark</span>
        <nav className="topnav">
          <a href="#/" className={view.type === 'home' ? 'active' : ''}>Home</a>
          <a href="#/docs/tutorial" className={view.type === 'doc' ? 'active' : ''}>Docs</a>
        </nav>
      </header>
      <main className="main">
        {view.type === 'home' && <Home />}
        {view.type === 'doc' && <DocPage slug={view.slug} />}
      </main>
      <footer className="footer">
        <span>Nomos · v0 · serving docs from <code>/api/docs</code></span>
      </footer>
    </div>
  )
}

export default App
