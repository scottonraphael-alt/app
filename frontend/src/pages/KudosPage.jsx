import "../Team.css";

import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Heart } from "lucide-react";

import TeamHeader from "../components/team/TeamHeader";
import {
  deleteKudos, errorMessage, fetchDirectory, fetchKudos, fetchKudosMeta, fetchKudosSummary,
  formatDate, sendKudos, teamKeys,
} from "../components/team/teamApi";

const SCOPES = [
  { value: "all", label: "Tout le mur" },
  { value: "received", label: "Reçus" },
  { value: "sent", label: "Envoyés" },
];

export default function KudosPage({ isResponsable = false, currentHelperId, helper }) {
  const me = currentHelperId || helper?.id;
  const qc = useQueryClient();
  const [scope, setScope] = useState("all");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("merci");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const meta = useQuery({ queryKey: ["team", "kudos", "meta"], queryFn: fetchKudosMeta, staleTime: Infinity });
  const people = useQuery({ queryKey: teamKeys.directory({}), queryFn: () => fetchDirectory({}) });
  const summary = useQuery({ queryKey: teamKeys.kudosSummary, queryFn: fetchKudosSummary });
  const wall = useInfiniteQuery({
    queryKey: teamKeys.kudos(scope), initialPageParam: undefined,
    queryFn: ({ pageParam }) => fetchKudos(scope, pageParam),
    getNextPageParam: (last) => (last.items.length >= 20 ? last.items[last.items.length - 1].id : undefined),
  });
  const items = useMemo(() => wall.data?.pages.flatMap((p) => p.items) ?? [], [wall.data]);
  const recipients = (people.data?.items ?? []).filter((p) => p.id !== me);
  const refresh = () => qc.invalidateQueries({ queryKey: ["team", "kudos"] });

  const send = useMutation({
    mutationFn: () => sendKudos({ to_id: to, category, message }),
    onSuccess: () => { toast.success("Remerciement envoyé."); setMessage(""); setError(""); refresh(); },
    onError: (err) => setError(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: deleteKudos,
    onSuccess: () => { toast.success("Remerciement supprimé."); refresh(); },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const s = summary.data;
  return (
    <section className="tm-page" data-testid="kudos-page">
      <TeamHeader eyebrow="ESPACE STAFF · ÉQUIPE" title="Mur des remerciements"
        intro={s ? `${s.received_30d} reçu${s.received_30d > 1 ? "s" : ""} ces 30 derniers jours · ${s.sent_today}/${s.daily_limit} envoyés aujourd'hui` : "Un mot sincère fait toute la différence."} />
      <div className="tm-layout">
        <aside className="tm-panel tm-sticky">
          <h2>Remercier un membre</h2>
          <form className="tm-form" onSubmit={(e) => { e.preventDefault(); setError(""); send.mutate(); }}>
            <label className="tm-label" htmlFor="kd-to">Destinataire</label>
            <select id="kd-to" className="tm-input" required value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="">Choisir…</option>
              {recipients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <label className="tm-label" htmlFor="kd-cat">Catégorie</label>
            <select id="kd-cat" className="tm-input" value={category} onChange={(e) => setCategory(e.target.value)}>
              {(meta.data?.items ?? [{ key: "merci", label: "Merci" }]).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            <label className="tm-label" htmlFor="kd-msg">Message ({message.length}/280)</label>
            <textarea id="kd-msg" className="tm-input tm-textarea" required maxLength={280} value={message}
              onChange={(e) => setMessage(e.target.value)} />
            {error && <p className="tm-error" role="alert">{error}</p>}
            <button type="submit" className="tm-btn tm-btn--primary" disabled={send.isPending || !to || !message.trim()}>
              <Heart size={16} aria-hidden="true" /> Envoyer
            </button>
          </form>
        </aside>
        <div>
          <div className="tm-toolbar" role="tablist" aria-label="Filtrer le mur">
            {SCOPES.map((f) => (
              <button key={f.value} type="button" role="tab" aria-selected={scope === f.value}
                className={`tm-filter${scope === f.value ? " is-on" : ""}`} onClick={() => setScope(f.value)}>{f.label}</button>
            ))}
          </div>
          {wall.isLoading && <p className="tm-state" role="status">Chargement…</p>}
          {wall.isError && <p className="tm-state tm-state--error" role="alert">{errorMessage(wall.error)}</p>}
          {!wall.isLoading && !wall.isError && items.length === 0 && <p className="tm-state">Aucun remerciement pour le moment.</p>}
          <ul className="tm-list" aria-live="polite">
            {items.map((k) => (
              <li className="tm-card" key={k.id}>
                <div className="tm-card-head">
                  <span className="tm-chip">{k.category_label}</span>
                  <span className="tm-meta"><strong>{k.from_name}</strong> → <strong>{k.to_name}</strong> · {formatDate(k.created_at)}</span>
                </div>
                <p className="tm-bio">{k.message}</p>
                {(isResponsable || k.from_id === me) && (
                  <div className="tm-actions">
                    <button type="button" className="tm-btn tm-btn--danger" onClick={() => remove.mutate(k.id)}>Supprimer</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {wall.hasNextPage && (
            <button type="button" className="tm-btn tm-more" disabled={wall.isFetchingNextPage} onClick={() => wall.fetchNextPage()}>Voir plus</button>
          )}
        </div>
      </div>
    </section>
  );
}
