import { useEffect, useState } from "react";
import { Bot, LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import { api, getErrorMessage } from "../../../api/client";
import { asList } from "./crisis";
import "./ai.css";

const INTENTS = [
  { value: "accueil", label: "Accueillir" },
  { value: "relance", label: "Relancer" },
  { value: "orientation", label: "Orienter" },
  { value: "cloture", label: "Clôturer" },
];

export default function CopilotPanel({ ticketId, onUseDraft }) {
  const [summary, setSummary] = useState(null);
  const [summarizing, setSummarizing] = useState(false);
  const [intent, setIntent] = useState("accueil");
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState("");
  const [hasDraft, setHasDraft] = useState(false);

  useEffect(() => { setSummary(null); setDraft(""); setHasDraft(false); }, [ticketId]);

  const summarize = async () => {
    setSummarizing(true);
    try {
      const { data } = await api.post(`/tickets/${ticketId}/copilot/summary`);
      setSummary(data);
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSummarizing(false);
    }
  };

  const propose = async () => {
    setDrafting(true);
    try {
      const { data } = await api.post(`/tickets/${ticketId}/copilot/draft`, { intent });
      setDraft(typeof data?.draft === "string" ? data.draft : "");
      setHasDraft(true);
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setDrafting(false);
    }
  };

  const use = () => {
    if (!draft.trim()) return;
    onUseDraft?.(draft.trim());
    setHasDraft(false);
    setDraft("");
  };

  return (
    <div className="tai-copilot" data-testid="copilot-panel">
      <div className="tai-copilot-block">
        <div className="tai-row">
          <button type="button" className="tai-btn" onClick={summarize} disabled={summarizing} data-testid="copilot-summary-button">
            {summarizing ? <LoaderCircle size={14} className="tai-spin" aria-hidden="true" /> : <Bot size={14} aria-hidden="true" />} Résumer
          </button>
        </div>
        {summary && (
          <div className="tai-summary" data-testid="copilot-summary">
            <p>{summary.summary}</p>
            {asList(summary.key_points).length > 0 && <ul>{asList(summary.key_points).map((point) => <li key={point}>{point}</li>)}</ul>}
            {summary.last_member_mood && <p className="tai-note">Ressenti du membre : {summary.last_member_mood}</p>}
          </div>
        )}
      </div>
      <div className="tai-copilot-block">
        <div className="tai-row">
          <label className="tai-label" htmlFor="tai-intent">Intention</label>
          <select id="tai-intent" className="tai-select" value={intent} onChange={(event) => setIntent(event.target.value)}>
            {INTENTS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <button type="button" className="tai-btn" onClick={propose} disabled={drafting} data-testid="copilot-draft-button">
            {drafting && <LoaderCircle size={14} className="tai-spin" aria-hidden="true" />} Proposer une réponse
          </button>
        </div>
        {hasDraft && (
          <div className="tai-draft" data-testid="copilot-draft">
            <label className="tai-label" htmlFor="tai-draft-text">Brouillon proposé (modifiable)</label>
            <textarea id="tai-draft-text" className="tai-textarea" rows={5} value={draft} onChange={(event) => setDraft(event.target.value)} />
            <p className="tai-note">Brouillon généré, relisez avant d’envoyer.</p>
            <div className="tai-row">
              <button type="button" className="tai-btn tai-btn-solid" onClick={use} disabled={!draft.trim()} data-testid="copilot-use-button">Utiliser</button>
              <button type="button" className="tai-btn" onClick={() => { setHasDraft(false); setDraft(""); }}>Ignorer</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
