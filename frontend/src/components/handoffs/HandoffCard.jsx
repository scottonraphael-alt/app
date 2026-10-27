import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Pencil, Pin, PinOff, RotateCcw, Trash2 } from "lucide-react";

import HandoffComposer from "./HandoffComposer";
import { PRIORITIES, formatDate } from "./handoffsApi";

const READ_DELAY_MS = 1200;

/** Carte d'une transmission ; se marque lue après 1,2 s dans le viewport ou au clic. */
export default function HandoffCard({ item, canManage, onRead, onResolve, onPin, onSave, onDelete, saving, saveError }) {
  const ref = useRef(null);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const unread = !item.read;

  useEffect(() => {
    const node = ref.current;
    if (!unread || !node || typeof IntersectionObserver === "undefined") return undefined;
    let timer = null;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && entry.intersectionRatio >= 0.6) {
        timer = timer || setTimeout(() => onRead(item.id), READ_DELAY_MS);
      } else if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    }, { threshold: [0.6] });
    observer.observe(node);
    return () => {
      observer.disconnect();
      if (timer) clearTimeout(timer);
    };
  }, [unread, item.id, onRead]);

  const prio = PRIORITIES.find((p) => p.value === item.priority)?.label || item.priority;
  const edited = item.updated_at && item.updated_at !== item.created_at && !item.resolved_at;

  if (editing) {
    return (
      <li className="ho-card is-editing">
        <HandoffComposer
          initial={item}
          submitLabel="Enregistrer"
          busy={saving}
          error={saveError}
          onCancel={() => setEditing(false)}
          onSubmit={(payload) => { onSave(item.id, payload, () => setEditing(false)); return false; }}
        />
      </li>
    );
  }

  const cls = ["ho-card", `ho-card--${item.priority}`];
  if (unread) cls.push("is-unread");
  if (item.resolved) cls.push("is-resolved");
  if (item.pinned) cls.push("is-pinned");

  return (
    <li
      ref={ref}
      className={cls.join(" ")}
      onClick={() => unread && onRead(item.id)}
      aria-label={`Transmission de ${item.author_name || "inconnu"}${unread ? ", non lue" : ""}`}
    >
      <header className="ho-card-head">
        <span className={`ho-prio ho-prio--${item.priority}`}>{prio}</span>
        {item.pinned && <span className="ho-flag"><Pin size={12} aria-hidden="true" /> Épinglée</span>}
        {unread && <span className="ho-flag ho-flag--new">Nouveau</span>}
        {item.resolved && <span className="ho-flag"><CheckCircle2 size={12} aria-hidden="true" /> Résolue</span>}
        <span className="ho-meta">
          <strong>{item.author_name || "Membre du staff"}</strong>
          <time dateTime={item.created_at}> · {formatDate(item.created_at)}</time>
          {edited && " · modifiée"}
        </span>
      </header>

      <p className="ho-body">{item.body}</p>

      {(item.tags?.length > 0 || item.related?.url) && (
        <div className="ho-chips">
          {item.tags?.map((tag) => <span key={tag} className="ho-tag">{tag}</span>)}
          {item.related?.url && (
            <Link className="ho-related" to={item.related.url} onClick={(e) => e.stopPropagation()}>
              {item.related.type} · {item.related.id} →
            </Link>
          )}
        </div>
      )}

      <footer className="ho-card-actions" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="ho-btn" onClick={() => onResolve(item)}>
          {item.resolved
            ? <><RotateCcw size={14} aria-hidden="true" /> Rouvrir</>
            : <><CheckCircle2 size={14} aria-hidden="true" /> Résoudre</>}
        </button>
        {canManage && !confirming && (
          <>
            <button type="button" className="ho-btn" onClick={() => onPin(item)}>
              {item.pinned
                ? <><PinOff size={14} aria-hidden="true" /> Désépingler</>
                : <><Pin size={14} aria-hidden="true" /> Épingler</>}
            </button>
            <button type="button" className="ho-btn" onClick={() => setEditing(true)}>
              <Pencil size={14} aria-hidden="true" /> Modifier
            </button>
            <button type="button" className="ho-btn ho-btn--danger" onClick={() => setConfirming(true)}>
              <Trash2 size={14} aria-hidden="true" /> Supprimer
            </button>
          </>
        )}
        {canManage && confirming && (
          <span className="ho-confirm" role="alert">
            Supprimer définitivement ?
            <button type="button" className="ho-btn ho-btn--danger" onClick={() => onDelete(item)}>Oui, supprimer</button>
            <button type="button" className="ho-btn" onClick={() => setConfirming(false)}>Annuler</button>
          </span>
        )}
      </footer>
    </li>
  );
}
