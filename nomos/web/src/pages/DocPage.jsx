import { useState, useEffect } from 'react'
import './DocPage.css'

function DocPage({ slug }) {
  const [html, setHtml] = useState(null)
  const [error, setError] = useState(null)
  const [index, setIndex] = useState([])

  // Load the docs index once so the sidebar can show siblings.
  useEffect(() => {
    fetch('/api/docs')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(setIndex)
      .catch(() => setIndex([]))
  }, [])

  // Load this doc whenever the slug changes.
  useEffect(() => {
    setHtml(null)
    setError(null)
    window.scrollTo(0, 0)
    fetch(`/api/docs/${slug}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.text()
      })
      .then(setHtml)
      .catch(e => setError(String(e)))
  }, [slug])

  return (
    <div className="doc-page">
      <aside className="doc-sidebar">
        <h3>Docs</h3>
        <ul>
          {index.map(d => (
            <li key={d.slug}>
              <a
                href={`#/docs/${d.slug}`}
                className={d.slug === slug ? 'active' : ''}
              >
                {d.title}
              </a>
            </li>
          ))}
        </ul>
      </aside>
      <article className="doc-main">
        {error && (
          <div className="doc-error">
            Couldn't load <code>{slug}</code>: {error}
          </div>
        )}
        {!html && !error && <div className="doc-loading">Loading…</div>}
        {html && (
          <div
            className="doc-content"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}
      </article>
    </div>
  )
}

export default DocPage
