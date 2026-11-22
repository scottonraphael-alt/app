/** Distinct decorative objects for each context. Hidden from assistive technology. */
export default function IrisIllustration({ kind = 'projects' }) {
  return <span className={`iris-illustration iris-illustration--${kind}`} aria-hidden="true">
    {kind === 'calendar' ? <>
      <span className="iris-calendar-stand"/>
      <span className="iris-calendar"><span className="iris-calendar-binding"/><span className="iris-calendar-grid">{Array.from({length:12},(_,i)=><span key={i} className={i===6?'is-marked':undefined}/>)}</span></span>
    </> : kind === 'tools' ? <>
      <span className="iris-console"><span className="iris-console-lights"><i/><i/><i/></span><span className="iris-console-controls"><span className="iris-console-slider"/><span className="iris-console-slider"/><span className="iris-console-slider"/></span></span>
      <span className="iris-console-dial"/>
    </> : <>
      <span className="iris-folder-back"/>
      <span className="iris-folder-file"><span/><span/><span/></span>
      <span className="iris-folder-front"><span/></span>
    </>}
  </span>;
}
