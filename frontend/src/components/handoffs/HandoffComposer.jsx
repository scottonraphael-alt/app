import { useId, useState } from "react";
import { Pin, Send, X } from "lucide-react";

import { MAX_BODY, MAX_TAG, MAX_TAGS, PRIORITIES } from "./handoffsApi";

/** Formulaire de création ou de modification d'une transmission. */
export default function HandoffComposer({ initial, textareaRef, submitLabel = "Transmettre", busy, error, onSubmit, onCancel }) {
  const uid = useId();
  const [body, setBody] = useState(initial?.body || "");
  const [priority, setPriority] = useState(initial?.priority || "info");
  const [tags, setTags] = useState(initial?.tags || []);
  const [tagDraft, setTagDraft] = useState("");
  const [pinned, setPinned] = useState(Boolean(initial?.pinned));

  const addTag = (raw) => {
    const tag = raw.trim().slice(0, MAX_TAG);
    if (!tag || tags.length >= MAX_TAGS) return;
    if (tags.some((t) => t.toLowerCase() === tag.toLowerCase())) return;
    setTags([...tags, tag]);
    setTagDraft("");
  };

  const onTagKey = (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addTag(tagDraft);
    } else if (event.key === "Backspace" && !tagDraft && tags.length) {
      setTags(tags.slice(0, -1));
    }
  };

  const submit = (event) => {
    event.preventDefault();
    const text = body.trim();
    if (!text || busy) return;
    const finalTags = tagDraft.trim() && tags.length < MAX_TAGS ? [...tags, tagDraft.trim().slice(0, MAX_TAG)] : tags;
    const ok = onSubmit({ body: text, priority, tags: finalTags, pinned });
    if (ok !== false && !initial) {
      setBody("");
      setTags([]);
      setTagDraft("");
      setPinned(false);
      setPriority("info");
    }
  };

  return (
    <form className="ho-composer" onSubmit={submit} aria-label={initial ? "Modifier la transmission" : "Nouvelle transmission"}>
      <label className="ho-label" htmlFor={`${uid}-body`}>Message</label>
      <textarea
        id={`${uid}-body`}
        ref={textareaRef}
        className="ho-textarea"
        value={body}
        maxLength={MAX_BODY}
        rows={4}
        required
        placeholder="Ce que l'équipe suivante doit savoir…"
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="ho-count" aria-hidden="true">{body.length} / {MAX_BODY}</div>

      <fieldset className="ho-fieldset">
        <legend className="ho-label">Priorité</legend>
        <div className="ho-segments" role="radiogroup" aria-label="Priorité">
          {PRIORITIES.map((p) => (
            <label key={p.value} className={`ho-segment ho-segment--${p.value}${priority === p.value ? " is-on" : ""}`}>
              <input
                type="radio"
                name={`${uid}-prio`}
                value={p.value}
                checked={priority === p.value}
                onChange={() => setPriority(p.value)}
              />
              {p.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="ho-label" htmlFor={`${uid}-tag`}>Étiquettes ({tags.length}/{MAX_TAGS})</label>
      <div className="ho-tags-input">
        {tags.map((tag) => (
          <span key={tag} className="ho-tag">
            {tag}
            <button type="button" aria-label={`Retirer l'étiquette ${tag}`} onClick={() => setTags(tags.filter((t) => t !== tag))}>
              <X size={12} aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          id={`${uid}-tag`}
          value={tagDraft}
          maxLength={MAX_TAG}
          disabled={tags.length >= MAX_TAGS}
          placeholder={tags.length >= MAX_TAGS ? "Maximum atteint" : "Ajouter (Entrée)"}
          onChange={(e) => setTagDraft(e.target.value)}
          onKeyDown={onTagKey}
          onBlur={() => addTag(tagDraft)}
        />
      </div>

      <div className="ho-composer-foot">
        <label className="ho-check">
          <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
          <Pin size={14} aria-hidden="true" /> Épingler en haut du fil
        </label>
        <div className="ho-actions">
          {onCancel && (
            <button type="button" className="ho-btn" onClick={onCancel}>Annuler</button>
          )}
          <button type="submit" className="ho-btn ho-btn--primary" disabled={busy || !body.trim()}>
            <Send size={14} aria-hidden="true" /> {busy ? "Envoi…" : submitLabel}
          </button>
        </div>
      </div>
      {error && <p className="ho-error" role="alert">{error}</p>}
    </form>
  );
}
