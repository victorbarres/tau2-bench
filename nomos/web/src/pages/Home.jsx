import { useState, useEffect } from 'react'
import './Home.css'

function Home() {
  const [docs, setDocs] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/docs')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setDocs)
      .catch(e => setError(String(e)))
  }, [])

  return (
    <div className="home">
      <section className="hero">
        <h1>Nomos</h1>
        <p className="lede">
          A runnable benchmark and authoring environment for logic-first
          agent tasks. Domains are governed by formally-stated laws;
          tasks are provably uniquely-solvable; agents are graded
          objectively.
        </p>
        <p className="status-line">
          v0 — currently serves the methodology, findings, and design
          docs. The benchmark UI (task authoring + agent runs + live
          trajectories) is in progress; see{' '}
          <a href="#/docs/benchmark">Benchmark</a> for the v0.5 plan
          and <a href="#/docs/open_decisions">Open Decisions</a> for
          what's still being settled.
        </p>
      </section>

      <section className="docs-section">
        <h2>Docs</h2>
        {error && <div className="error">Couldn't load docs index: {error}</div>}
        {!docs && !error && <div className="loading">Loading…</div>}
        {docs && (
          <ul className="doc-list">
            {docs.map(d => (
              <li key={d.slug}>
                <a href={`#/docs/${d.slug}`} className="doc-card">
                  <div className="doc-title">{d.title}</div>
                  {d.blurb && <div className="doc-blurb">{d.blurb}</div>}
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export default Home
