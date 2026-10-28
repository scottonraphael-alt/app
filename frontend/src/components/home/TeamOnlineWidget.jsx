import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { agoLabel } from "./homeUtils";

export default function TeamOnlineWidget({ helperId, enabled = true }) {
  const query = useQuery({
    queryKey: ["home", "team-online", helperId],
    enabled: Boolean(helperId && enabled),
    queryFn: async ({ signal }) => (await api.get("/presence/team", { signal })).data,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const members = query.data?.members || [];
  const active = query.data?.active_count || 0;

  return (
    <section className="hm-card hm-team" aria-labelledby="hm-team-title" data-testid="team-online-widget">
      <div className="hm-card-head">
        <h2 id="hm-team-title">Équipe en ligne</h2>
        {query.isSuccess && (
          <span className="hm-count" aria-label={`${active} en ligne`}>{active}</span>
        )}
      </div>
      {query.isPending ? (
        <p className="hm-muted" role="status">Chargement…</p>
      ) : query.isError ? (
        <p className="hm-muted" role="alert">Présence indisponible.</p>
      ) : members.length === 0 ? (
        <p className="hm-muted">Personne d’actif récemment.</p>
      ) : (
        <ul className="hm-team-list">
          {members.map((m) => (
            <li key={m.user_id}>
              <span className={`hm-dot hm-dot--${m.status}`} aria-hidden="true" />
              {m.avatar_url ? (
                <img className="hm-avatar" src={m.avatar_url} alt="" width="28" height="28" loading="lazy" />
              ) : (
                <span className="hm-avatar hm-avatar--fallback" aria-hidden="true">
                  {(m.name || "?").slice(0, 1).toUpperCase()}
                </span>
              )}
              <span className="hm-team-name">{m.name || "Membre"}{m.is_me ? " (toi)" : ""}</span>
              <span className="hm-muted hm-team-status">
                {m.status === "active" ? "En ligne" : agoLabel(m.last_seen)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
