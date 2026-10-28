import { useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import "../../Team.css";
import {
  DURATIONS, STATES, clearMyStatus, errorMessage, fetchMyStatus, saveMyStatus, teamKeys,
} from "./teamApi";

/** Sélecteur de statut personnel, destiné à la barre du haut. */
export default function StatusPicker() {
  const qc = useQueryClient();
  const uid = useId();
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [state, setState] = useState("disponible");
  const [message, setMessage] = useState("");
  const [duration, setDuration] = useState("");

  const query = useQuery({ queryKey: teamKeys.myStatus, queryFn: fetchMyStatus, staleTime: 60000, retry: false });
  const current = query.data;

  useEffect(() => {
    if (open && current) { setState(current.state); setMessage(current.message || ""); setDuration(""); }
  }, [open, current]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    const onClick = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, [open]);

  const done = (data) => { qc.setQueryData(teamKeys.myStatus, data); qc.invalidateQueries({ queryKey: ["team", "directory"] }); setOpen(false); };
  const save = useMutation({
    mutationFn: () => saveMyStatus({
      state, message, ...(duration && state !== "disponible" ? { expires_in_minutes: Number(duration) } : {}),
    }),
    onSuccess: (data) => { done(data); toast.success("Statut mis à jour."); },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const clear = useMutation({
    mutationFn: clearMyStatus,
    onSuccess: () => { done({ state: "disponible", label: "Disponible", message: "" }); toast.success("Statut réinitialisé."); },
    onError: (err) => toast.error(errorMessage(err)),
  });

  if (query.isError) return null;
  const st = current?.state || "disponible";

  return (
    <div className="tm-status" ref={rootRef}>
      <button
        type="button" className="tm-status-btn" aria-haspopup="dialog" aria-expanded={open}
        onClick={() => setOpen((v) => !v)} data-testid="status-picker"
      >
        <span className={`tm-dot tm-dot--${st}`} aria-hidden="true" />
        <span>{current?.label || "Disponible"}</span>
      </button>
      {open && (
        <div className="tm-status-pop" role="dialog" aria-label="Mon statut">
          <fieldset className="tm-fieldset">
            <legend className="tm-label">Mon statut</legend>
            <div className="tm-segments">
              {STATES.map((s) => (
                <label key={s.value} className={`tm-segment${state === s.value ? " is-on" : ""}`}>
                  <input type="radio" name={`${uid}-state`} value={s.value} checked={state === s.value} onChange={() => setState(s.value)} />
                  <span className={`tm-dot tm-dot--${s.value}`} aria-hidden="true" />{s.label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="tm-label" htmlFor={`${uid}-msg`}>Message (facultatif)</label>
          <input id={`${uid}-msg`} className="tm-input" maxLength={80} value={message}
            onChange={(e) => setMessage(e.target.value)} placeholder="Ex. en réunion jusqu'à 18 h" />
          {state !== "disponible" && (
            <>
              <label className="tm-label" htmlFor={`${uid}-dur`}>Expire après</label>
              <select id={`${uid}-dur`} className="tm-input" value={duration} onChange={(e) => setDuration(e.target.value)}>
                {DURATIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </>
          )}
          <div className="tm-actions">
            <button type="button" className="tm-btn tm-btn--primary" disabled={save.isPending} onClick={() => save.mutate()}>Enregistrer</button>
            <button type="button" className="tm-btn" disabled={clear.isPending} onClick={() => clear.mutate()}>Réinitialiser</button>
          </div>
        </div>
      )}
    </div>
  );
}
