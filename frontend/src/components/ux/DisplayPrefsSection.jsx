import { BellOff, Type } from "lucide-react";

import useDisplayPrefs, { SCALE_MAX, SCALE_MIN } from "../../hooks/useDisplayPrefs";
import useFocusMode, { FOCUS_DURATIONS } from "../../hooks/useFocusMode";
import "./ux.css";

export default function DisplayPrefsSection() {
  const { prefs, update, reset } = useDisplayPrefs();
  const focus = useFocusMode();
  return (
    <section className="hp-extra-card ux-prefs" aria-labelledby="ux-prefs-title" data-testid="helper-display-prefs">
      <div className="hp-extra-header"><h2 id="ux-prefs-title"><Type size={16} aria-hidden="true" /> Affichage et concentration</h2></div>
      <div className="ux-prefs-body">
        <fieldset>
          <legend>Densité</legend>
          {[["confort", "Confort"], ["compact", "Compact"]].map(([value, label]) => (
            <label key={value}><input type="radio" name="ux-density" checked={prefs.density === value} onChange={() => update({ density: value })} /> {label}</label>
          ))}
        </fieldset>
        <label className="ux-scale">Taille du texte : <strong>{prefs.scale} %</strong>
          <input type="range" min={SCALE_MIN} max={SCALE_MAX} step={5} value={prefs.scale} onChange={(e) => update({ scale: Number(e.target.value) })} />
        </label>
        <button type="button" className="ux-btn" onClick={reset}>Réinitialiser</button>
        <fieldset>
          <legend><BellOff size={13} aria-hidden="true" /> Mode concentration</legend>
          <p className="ux-note">Coupe les badges et sons non urgents. Les crises passent toujours.</p>
          {focus.active ? (
            <button type="button" className="ux-btn" onClick={focus.stop}>Arrêter la concentration</button>
          ) : FOCUS_DURATIONS.map((m) => (
            <button key={m} type="button" className="ux-btn" onClick={() => focus.start(m)}>{m >= 60 ? `${m / 60} h` : `${m} min`}</button>
          ))}
        </fieldset>
      </div>
    </section>
  );
}
