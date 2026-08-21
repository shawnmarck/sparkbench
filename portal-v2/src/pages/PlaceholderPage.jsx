export function PlaceholderPage({ title, legacyHash }) {
  return (
    <div>
      <div className="page-head">
        <h1>{title}</h1>
        <p>Not ported yet. The control plane is unchanged.</p>
      </div>
      <div className="placeholder">
        Use the <a href={`/${legacyHash || ''}`}>legacy {title}</a> page for now.
      </div>
    </div>
  )
}
