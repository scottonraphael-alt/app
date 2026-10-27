import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ClipboardCopy, FileText, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api, getErrorMessage } from "../../../api/client";
import CopilotPanel from "./CopilotPanel";
import TemplatesManager from "./TemplatesManager";
import { asList } from "./crisis";
import "./ai.css";

const SLASH = /(^|\s)\/([\w-]*)$/;
const norm = (value) => String(value || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Zone de préparation de réponse : copilote + modèles. Rien n’est envoyé depuis Iris. */
export default function ReplyComposer({ ticketId, memberName, helperName, helperId, canShare, onTyping }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [templates, setTemplates] = useState([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [slash, setSlash] = useState(false);
  const [active, setActive] = useState(0);
  const [manage, setManage] = useState(false);
  const areaRef = useRef(null);

  const loadTemplates = useCallback(async () => {
    try {
      const { data } = await api.get("/reply-templates");
      setTemplates(asList(data?.items));
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  }, []);

  useEffect(() => { setText(""); setPickerOpen(false); }, [ticketId]);
  useEffect(() => { if (open && templates.length === 0) loadTemplates(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = norm(query.replace(/^\//, ""));
    if (!q) return templates;
    return templates.filter((item) => norm(`${item.title} ${item.shortcut || ""} ${item.category || ""} ${item.body}`).includes(q));
  }, [templates, query]);

  const closePicker = () => { setPickerOpen(false); setSlash(false); setQuery(""); setActive(0); };

  const insert = (value, replaceSlash) => {
    const area = areaRef.current;
    const caret = area?.selectionStart ?? text.length;
    const before = text.slice(0, caret);
    const after = text.slice(caret);
    const start = replaceSlash ? before.replace(SLASH, "$1") : before;
    const next = `${start}${value}${after}`;
    setText(next);
    onTyping?.();
    window.setTimeout(() => {
      if (!area) return;
      const pos = start.length + value.length;
      area.focus();
      area.setSelectionRange?.(pos, pos);
    }, 0);
  };

  const pick = async (item) => {
    const wasSlash = slash;
    closePicker();
    try {
      const { data } = await api.post(`/reply-templates/${item.id}/render`, { variables: { pseudo: memberName || "", helper: helperName || "" } });
      insert(data?.text || "", wasSlash);
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  const onChange = (event) => {
    const value = event.target.value;
    setText(value);
    onTyping?.();
    const match = value.slice(0, event.target.selectionStart ?? value.length).match(SLASH);
    if (match) { setSlash(true); setPickerOpen(true); setQuery(match[2]); setActive(0); }
    else if (slash) closePicker();
  };

  const onKeyDown = (event) => {
    if (!pickerOpen || !slash) return;
    if (event.key === "ArrowDown") { event.preventDefault(); setActive((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0))); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (event.key === "Enter" && filtered[active]) { event.preventDefault(); pick(filtered[active]); }
    else if (event.key === "Escape") { event.preventDefault(); closePicker(); }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Réponse copiée : collez-la dans Discord.");
    } catch {
      areaRef.current?.select();
      toast.error("Copie impossible, sélectionnez le texte manuellement.");
    }
  };

  const useDraft = (draft) => {
    setText((current) => (current.trim() ? `${current.trimEnd()}\n\n${draft}` : draft));
    onTyping?.();
    toast.success("Brouillon inséré. Relisez-le avant de l’envoyer.");
    window.setTimeout(() => areaRef.current?.focus(), 0);
  };

  return (
    <section className="tai-composer" data-testid="reply-composer" aria-label="Préparer une réponse">
      <button type="button" className="tai-composer-toggle" aria-expanded={open} aria-controls="tai-composer-body" onClick={() => setOpen((value) => !value)}>
        <FileText size={16} aria-hidden="true" /> Préparer une réponse <ChevronDown size={16} className={`tai-chevron${open ? " is-open" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="tai-composer-body" id="tai-composer-body">
          <CopilotPanel ticketId={ticketId} onUseDraft={useDraft} />
          <div className="tai-row tai-row-between">
            <label className="tai-label" htmlFor="tai-reply-text">Ma réponse (tapez « / » pour insérer un modèle)</label>
            <div className="tai-row">
              <button type="button" className="tai-btn" aria-haspopup="listbox" aria-expanded={pickerOpen && !slash} onClick={() => { if (pickerOpen) closePicker(); else { setSlash(false); setPickerOpen(true); setQuery(""); setActive(0); } }} data-testid="templates-button">Modèles</button>
              <button type="button" className="tai-icon-btn" aria-label="Gérer mes modèles" onClick={() => setManage(true)}><Settings2 size={16} /></button>
            </div>
          </div>
          {pickerOpen && (
            <div className="tai-picker" data-testid="template-picker">
              {!slash && <input className="tai-input" type="search" aria-label="Filtrer les modèles" placeholder="Filtrer les modèles…" value={query} autoFocus onChange={(event) => { setQuery(event.target.value); setActive(0); }} />}
              <ul role="listbox" aria-label="Modèles de réponse">
                {filtered.length === 0 && <li className="tai-note" role="presentation">Aucun modèle trouvé.</li>}
                {filtered.map((item, index) => (
                  <li key={item.id} role="option" aria-selected={index === active} className={index === active ? "is-active" : ""} onMouseDown={(event) => { event.preventDefault(); pick(item); }}>
                    <strong>{item.title}</strong>{item.shortcut && <code>{item.shortcut}</code>}
                    <span>{item.body.slice(0, 90)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <textarea id="tai-reply-text" ref={areaRef} className="tai-textarea" rows={6} value={text} onChange={onChange} onKeyDown={onKeyDown} />
          <div className="tai-row tai-row-between">
            <p className="tai-note">Iris n’envoie rien : copiez le texte puis envoyez-le dans Discord.</p>
            <button type="button" className="tai-btn tai-btn-solid" onClick={copy} disabled={!text.trim()}><ClipboardCopy size={14} aria-hidden="true" /> Copier</button>
          </div>
        </div>
      )}
      {manage && <TemplatesManager templates={templates} canShare={canShare} helperId={helperId} onClose={() => setManage(false)} onChanged={loadTemplates} />}
    </section>
  );
}
