import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import TagFilter from "../components/tickets/extras/TagFilter";
import useTicketTags from "../components/tickets/extras/useTicketTags";
import "../components/tickets/extras/extras.css";

const COLUMNS = [
  { key: "unassigned", label: "Non attribué" },
  { key: "en cours", label: "En cours" },
  { key: "en attente de réponse", label: "En attente du membre" },
  { key: "à conclure", label: "À clôturer" },
];

const columnOf = (t) => (!t.assigned_helper?.id ? "unassigned" : t.follow_up_status || "en attente de réponse");
const displayName = (m) => m?.display_name || m?.global_name || m?.username || "Membre";

export default function TicketsKanbanPage({ isAdmin = false, helper, tickets: initial }) {
  const [tickets, setTickets] = useState(initial || []);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState("");
  const [dragId, setDragId] = useState(null);
  const [overCol, setOverCol] = useState(null);
  const [tag, setTag] = useState("");
  const { tags, assignments } = useTicketTags();

  useEffect(() => {
    document.body.classList.add("tx-kanban-no-nav");
    return () => document.body.classList.remove("tx-kanban-no-nav");
  }, []);

  useEffect(() => {
    if (initial) return undefined;
    let active = true;
    api.get("/tickets").then((r) => { if (active) setTickets(r.data); })
      .catch((e) => { if (active) setError(getErrorMessage(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [initial]);

  const grouped = useMemo(() => {
    const out = Object.fromEntries(COLUMNS.map((c) => [c.key, []]));
    tickets.filter((t) => t.status === "active" && (!tag || (assignments[t.id] || []).includes(tag)))
      .forEach((t) => (out[columnOf(t)] || out["en attente de réponse"]).push(t));
    return out;
  }, [tickets, tag, assignments]);

  // Une colonne n'accepte un dépôt que si l'action existe pour ce rôle ; sinon elle est en lecture seule.
  const canDropTo = useCallback((ticket, target) => {
    if (!ticket || columnOf(ticket) === target) return false;
    if (target === "unassigned") return isAdmin;
    if (columnOf(ticket) === "unassigned") return isAdmin && Boolean(helper?.id);
    return true;
  }, [isAdmin, helper]);

  const move = async (ticket, target) => {
    if (!canDropTo(ticket, target)) {
      if (columnOf(ticket) !== target) toast.error("Seul un coordinateur peut modifier l'attribution.");
      return;
    }
    const before = ticket;
    try {
      let next = { ...ticket };
      if (target === "unassigned") {
        await api.patch(`/admin/tickets/${ticket.id}/assignment`, { helper_id: null });
        next.assigned_helper = null;
      } else {
        if (columnOf(ticket) === "unassigned") {
          await api.patch(`/admin/tickets/${ticket.id}/assignment`, { helper_id: helper.id });
          next.assigned_helper = { id: helper.id, username: helper.username, display_name: helper.global_name };
        }
        await api.patch(`/tickets/${ticket.id}`, { follow_up_status: target });
        next.follow_up_status = target;
      }
      setTickets((c) => c.map((t) => (t.id === ticket.id ? next : t)));
    } catch (e) {
      setTickets((c) => c.map((t) => (t.id === before.id ? before : t)));
      toast.error(getErrorMessage(e));
    }
  };

  return (
    <section className="tx-kanban" data-testid="tickets-kanban-page">
      <header className="tx-k-header">
        <div>
          <h1>Tableau des suivis</h1>
          <p className="tx-k-intro">Glissez un dossier d'une colonne à l'autre pour changer son statut.</p>
        </div>
        <Link to="/" className="tx-k-home">Accueil <ArrowRight size={18} aria-hidden="true" /></Link>
      </header>
      <TagFilter tags={tags} value={tag} onChange={setTag} />
      {error && <p className="tx-k-error" role="alert">{error}</p>}
      {loading ? <p role="status">Chargement…</p> : (
        <div className="tx-k-board">
          {COLUMNS.map((col) => {
            const dragging = tickets.find((t) => t.id === dragId);
            const droppable = dragging ? canDropTo(dragging, col.key) : false;
            return (
              <section key={col.key} className={`tx-k-col${overCol === col.key && droppable ? " is-over" : ""}`} aria-label={col.label}
                onDragOver={(e) => { if (droppable) { e.preventDefault(); setOverCol(col.key); } }}
                onDragLeave={() => setOverCol(null)}
                onDrop={(e) => { e.preventDefault(); setOverCol(null); if (dragging) move(dragging, col.key); setDragId(null); }}>
                <h2>{col.label} <span>{grouped[col.key].length}</span></h2>
                {col.key === "unassigned" && !isAdmin && <p className="tx-k-readonly">Lecture seule : l'attribution est réservée aux coordinateurs.</p>}
                {grouped[col.key].map((t) => (
                  <Link key={t.id} to={`/tickets/${t.id}`} draggable className={`tx-k-card${dragId === t.id ? " is-dragging" : ""}`}
                    onDragStart={(e) => { setDragId(t.id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", t.id); }}
                    onDragEnd={() => { setDragId(null); setOverCol(null); }}>
                    <strong>{displayName(t.member)}</strong>
                    <small>{t.title || t.channel_name}</small>
                    {t.assigned_helper && <small>Interlocuteur : {displayName(t.assigned_helper)}</small>}
                  </Link>
                ))}
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
