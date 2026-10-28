// Importé en premier : Casier.css fournit les jetons --cz-* (clair et sombre) et l'en-tête de page.
import "../Casier.css";
import "../components/casier/casier-detail.css";
import "../Member360.css";

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useInfiniteQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  FilePenLine,
  Loader2,
  MessageSquareText,
  ShieldAlert,
  ShieldCheck,
  Ticket,
  Gavel,
} from "lucide-react";

import MemberAvatar from "../components/casier/MemberAvatar";
import StatusPill from "../components/casier/StatusPill";
import { errorMessage, errorStatus } from "../components/casier/casierApi";
import { formatDate, formatRelative, memberHandle, memberName, plural } from "../components/casier/formatters";
import { api } from "../api/client";

const SNOWFLAKE = /^\d{17,20}$/;
const PAGE_SIZE = 30;

const TYPE_META = {
  case_ticket: { label: "Dossier", icon: Ticket },
  verification: { label: "Admission", icon: ShieldCheck },
  sanction: { label: "Sanction", icon: Gavel },
  ai_flag: { label: "Signalement IA", icon: Bot },
  ticket: { label: "Ticket", icon: Ticket },
  fiche: { label: "Fiche S", icon: FilePenLine },
  note: { label: "Information", icon: MessageSquareText },
};

// Filtres : « fiches » regroupe fiches S et informations ajoutées aux sanctions.
const FILTERS = [
  { value: "all", label: "Tout", types: null },
  { value: "case_ticket", label: "Dossiers", types: ["case_ticket"] },
  { value: "verification", label: "Admission", types: ["verification"] },
  { value: "sanction", label: "Sanctions", types: ["sanction"] },
  { value: "ai_flag", label: "Signalements IA", types: ["ai_flag"] },
  { value: "ticket", label: "Tickets", types: ["ticket"] },
  { value: "fiche", label: "Fiches", types: ["fiche", "note"] },
];

const SEVERITY_LABELS = {
  info: "Information",
  low: "Gravité faible",
  medium: "Gravité moyenne",
  high: "Gravité élevée",
  critical: "Gravité critique",
};

async function fetchMember360(discordId, { before, signal }) {
  const params = { limit: PAGE_SIZE };
  if (before) params.before = before;
  const { data } = await api.get(`/members/${encodeURIComponent(discordId)}/360`, { params, signal });
  return data;
}

// Pas de nouvel essai sur une erreur 4xx ; le 503 (journalisation indisponible) se réessaie à la main.
function retryTransient(failureCount, error) {
  const status = errorStatus(error);
  if (status && status < 500) return false;
  if (status === 503) return false;
  return failureCount < 1;
}

function internalPath(url) {
  return typeof url === "string" && url.startsWith("/") && !url.startsWith("//") ? url : null;
}

function Header({ back = true }) {
  return (
    <header className="cz-header">
      <div className="cz-header-copy">
        <p className="cz-eyebrow">ESPACE OPÉRATEUR · MODÉRATION</p>
        <h1>Vue membre 360°</h1>
        <p className="cz-intro">
          Sanctions, signalements de l'IA, fiches et tickets d'un membre, sur une seule frise chronologique.
        </p>
      </div>
      <div className="cz-header-actions">
        {back && (
          <Link to="/moderation/casiers" className="cz-button">
            <ArrowLeft size={16} aria-hidden="true" />
            Casiers
          </Link>
        )}
        <Link to="/" className="cz-home">
          Accueil
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}

function Stat({ label, value }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="m3-stat">
      <dd>{Number(value).toLocaleString("fr-FR")}</dd>
      <dt>{label}</dt>
    </div>
  );
}

function TimelineItem({ entry }) {
  const meta = TYPE_META[entry.type] || { label: "Événement", icon: ShieldCheck };
  const Icon = meta.icon;
  const severity = SEVERITY_LABELS[entry.severity] ? entry.severity : "info";
  const path = internalPath(entry.url);

  return (
    <li className={`m3-item m3-item--${severity}`}>
      <span className="m3-dot" aria-hidden="true">
        <Icon size={15} />
      </span>
      <div className="m3-item-body">
        <p className="m3-item-head">
          <span className="m3-type">{meta.label}</span>
          <span className={`m3-sev m3-sev--${severity}`}>{SEVERITY_LABELS[severity]}</span>
          <time dateTime={entry.at} className="m3-time">
            {formatDate(entry.at)}
          </time>
        </p>
        <p className="m3-item-title">{entry.title}</p>
        {entry.detail && <p className="m3-item-detail">{entry.detail}</p>}
        {path && (
          <Link to={path} className="m3-link">
            Ouvrir
            <ArrowRight size={14} aria-hidden="true" />
            <span className="cz-sr-only"> : {entry.title}</span>
          </Link>
        )}
      </div>
    </li>
  );
}

function MemberView({ discordId }) {
  const [filter, setFilter] = useState("all");

  const query = useInfiniteQuery({
    queryKey: ["member-360", discordId],
    queryFn: ({ pageParam, signal }) => fetchMember360(discordId, { before: pageParam, signal }),
    initialPageParam: undefined,
    getNextPageParam: (last) => last?.next_before || undefined,
    retry: retryTransient,
    refetchOnWindowFocus: false, // chaque lecture est journalisée
    staleTime: 60_000,
  });

  const pages = useMemo(() => query.data?.pages || [], [query.data]);
  const first = pages[0] || null;
  const member = first?.member || { id: discordId };
  const summary = first?.summary || {};
  const timeline = useMemo(() => pages.flatMap((page) => page?.timeline || []), [pages]);

  const active = FILTERS.find((item) => item.value === filter) || FILTERS[0];
  const visible = active.types ? timeline.filter((entry) => active.types.includes(entry.type)) : timeline;

  // Types présents dans la réponse : un filtre sans accès n'est pas proposé.
  const allowedTypes = useMemo(() => {
    const set = new Set();
    if (summary.sanctions_count !== null && summary.sanctions_count !== undefined) {
      ["sanction", "ai_flag", "fiche", "note"].forEach((type) => set.add(type));
    }
    if (summary.tickets_count !== null && summary.tickets_count !== undefined) set.add("ticket");
    if (summary.case_tickets_count != null) set.add("case_ticket");
    if (summary.verification_forms_count != null) set.add("verification");
    return set;
  }, [summary.sanctions_count, summary.tickets_count, summary.case_tickets_count, summary.verification_forms_count]);
  const filters = FILTERS.filter((item) => !item.types || item.types.some((type) => allowedTypes.has(type)));

  if (query.isPending) {
    return (
      <div className="cz-card m3-state" role="status" aria-live="polite">
        <Loader2 size={18} className="cz-spin" aria-hidden="true" />
        Chargement de la vue membre…
      </div>
    );
  }

  if (query.isError && !first) {
    const status = errorStatus(query.error);
    return (
      <div className="cz-card cz-empty cz-empty--error" role="alert">
        <ShieldAlert size={26} aria-hidden="true" />
        <h3>
          {status === 403
            ? "Accès refusé."
            : status === 503
              ? "Consultation impossible pour le moment."
              : "Impossible de charger cette vue."}
        </h3>
        <p>{errorMessage(query.error)}</p>
        {status !== 403 && (
          <div className="cz-empty-actions">
            <button type="button" className="cz-button" onClick={() => query.refetch()}>
              Réessayer
            </button>
          </div>
        )}
      </div>
    );
  }

  const handle = memberHandle(member);
  const lastActivity = formatRelative(summary.last_activity_at);

  return (
    <div className="m3-layout">
      <section className="cz-card m3-identity" aria-labelledby="m3-name">
        <MemberAvatar member={member} size={64} shape="square" />
        <div className="m3-identity-copy">
          <h2 id="m3-name">{memberName(member)}</h2>
          {handle && <p className="m3-handle">{handle}</p>}
          <p className="m3-id">
            ID Discord : <code className="cz-mono">{discordId}</code>
          </p>
        </div>
        <div className="m3-identity-side">
          {summary.status && (
            <>
              <span className="cz-sr-only">Statut :</span>
              <StatusPill status={summary.status} size="lg" title="Statut = sanction la plus grave reçue" />
            </>
          )}
        </div>
      </section>

      <section className="cz-card" aria-label="Résumé">
        <dl className="m3-stats">
          <Stat label={plural(summary.sanctions_count, "sanction", "sanctions").replace(/^[\d\s  ]+/, "")} value={summary.sanctions_count} />
          <Stat label="Signalements IA" value={summary.ai_flags_count} />
          {summary.case_tickets_count != null && <Stat label="Dossiers" value={summary.case_tickets_count} />}
          {summary.verification_forms_count != null && <Stat label="Formulaires" value={summary.verification_forms_count} />}
          <Stat label={plural(summary.tickets_count, "ticket", "tickets").replace(/^[\d\s  ]+/, "")} value={summary.tickets_count} />
          <Stat label={plural(summary.fiches_count, "fiche S", "fiches S").replace(/^[\d\s  ]+/, "")} value={summary.fiches_count} />
        </dl>
        {lastActivity && <p className="m3-last">Dernière activité {lastActivity}</p>}
      </section>

      <section className="cz-card m3-timeline" aria-labelledby="m3-timeline-title">
        <div className="m3-timeline-head">
          <h2 id="m3-timeline-title">Frise chronologique</h2>
          <div className="m3-filters" role="group" aria-label="Filtrer la frise par type">
            {filters.map((item) => (
              <button
                key={item.value}
                type="button"
                className="m3-filter"
                aria-pressed={filter === item.value}
                onClick={() => setFilter(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {visible.length ? (
          <ol className="m3-list">
            {visible.map((entry) => (
              <TimelineItem key={`${entry.type}-${entry.id}-${entry.at}`} entry={entry} />
            ))}
          </ol>
        ) : (
          <div className="cz-empty cz-empty--compact">
            <p>
              {timeline.length
                ? "Aucun événement de ce type parmi ceux déjà chargés."
                : "Aucun événement pour ce membre."}
            </p>
          </div>
        )}

        {query.isFetchNextPageError && (
          <p className="m3-alert" role="alert">
            {errorMessage(query.error)}
          </p>
        )}

        {query.hasNextPage && (
          <div className="m3-more">
            <button
              type="button"
              className="cz-button"
              onClick={() => query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
            >
              {query.isFetchingNextPage && <Loader2 size={16} className="cz-spin" aria-hidden="true" />}
              Charger plus
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

export default function Member360Page() {
  const { memberId } = useParams();
  const discordId = String(memberId || "");
  const valid = SNOWFLAKE.test(discordId);

  useEffect(() => {
    document.body.classList.add("casier-no-nav");
    return () => document.body.classList.remove("casier-no-nav");
  }, []);

  return (
    <section className="cz-page m3-page" data-testid="member-360-page">
      <Header />
      {valid ? (
        <MemberView key={discordId} discordId={discordId} />
      ) : (
        <div className="cz-card cz-empty cz-empty--error" role="alert">
          <ShieldAlert size={26} aria-hidden="true" />
          <h3>Identifiant Discord invalide.</h3>
          <p>Ouvrez la vue 360° depuis la fiche d'un casier.</p>
        </div>
      )}
      <p className="m3-audit">Consultation journalisée.</p>
    </section>
  );
}
