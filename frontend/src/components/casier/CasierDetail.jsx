import "./casier-detail.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, Eye, FilePenLine, MicOff, Orbit, Plus, ScrollText, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import AddSanctionDialog from "./AddSanctionDialog";
import AiFlagList from "./AiFlagList";
import CasierMetrics from "./CasierMetrics";
import FicheSEditorDialog from "./FicheSEditorDialog";
import FicheSList from "./FicheSList";
import HistoryPanel from "./history/HistoryPanel";
import MemberAvatar from "./MemberAvatar";
import SanctionTimeline from "./SanctionTimeline";
import StatusPill from "./StatusPill";
import { casierKeys, errorMessage, errorStatus, getCasier } from "./casierApi";
import { PENDING_POLL_INTERVAL_MS, PENDING_POLL_MAX_MS } from "./casierConstants";
import {
  authorName,
  formatDate,
  formatRelative,
  formatUntil,
  isBotAuthor,
  memberHandle,
  memberName,
  plural,
} from "./formatters";

const SNOWFLAKE = /^\d{17,20}$/;
const FLAGS_EMPTY_MESSAGE = "Aucun message de ce membre n'a été signalé par l'IA.";
const COPIED_RESET_MS = 2000;

function hasPendingAttachment(casier) {
  return Boolean(
    casier?.sanctions?.some((sanction) => sanction.attachments?.some((item) => item.status === "pending"))
  );
}

// Pas de nouvel essai sur une erreur 4xx (404, 400…).
function retryServerErrors(failureCount, error) {
  const status = errorStatus(error);
  if (status && status < 500) return false;
  return failureCount < 2;
}

function isFuture(value) {
  const time = Date.parse(value || "");
  return Number.isFinite(time) && time > Date.now();
}

async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Repli ci-dessous (contexte non sécurisé, permission refusée).
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(area);
    return copied;
  } catch {
    return false;
  }
}

function creatorLabel(author) {
  if (!author) return "";
  if (isBotAuthor(author)) return "par OasisBot";
  const name = authorName(author, "");
  return name ? `par ${name}` : "";
}

function DetailLoading() {
  return (
    <div className="cz-detail" aria-busy="true">
      <p className="cz-sr-only" role="status">
        Chargement du casier…
      </p>
      <div className="cz-card cz-skeleton-card" aria-hidden="true">
        <div className="cz-skeleton-row cz-skeleton-row--flush">
          <span className="cz-skeleton cz-skeleton--avatar" />
          <div className="cz-skeleton-stack">
            <span className="cz-skeleton cz-skeleton--title" />
            <span className="cz-skeleton cz-skeleton--short" />
          </div>
        </div>
        <span className="cz-skeleton cz-skeleton--short" />
      </div>
      <div className="cz-detail-skeleton" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <div key={index} className="cz-card cz-skeleton-card">
            <span className="cz-skeleton cz-skeleton--title" />
            <span className="cz-skeleton cz-skeleton--block" />
          </div>
        ))}
      </div>
    </div>
  );
}

function TabCount({ value, tone = "muted", srSuffix = "" }) {
  return (
    <span className={`cz-tab-count${tone === "muted" ? " cz-tab-count--muted" : ""}`}>
      {value}
      {srSuffix && <span className="cz-sr-only">{srSuffix}</span>}
    </span>
  );
}

// Fiche d'un membre : identité, métriques, onglets Historique / Fiches S / Signalements IA, modales.
export default function CasierDetail({
  casierId,
  tab = "historique",
  onTabChange,
  highlightSanctionId = null,
  highlightFlagId = null,
  onNavigate,
  onBack,
}) {
  const pollStartRef = useRef(null);
  const copiedTimerRef = useRef(null);
  const [copied, setCopied] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [ficheEditor, setFicheEditor] = useState(null);
  const [pollExpired, setPollExpired] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0);

  const query = useQuery({
    queryKey: casierKeys.detail(casierId),
    queryFn: ({ signal }) => getCasier(casierId, { signal }),
    retry: retryServerErrors,
    // Sonde tant qu'un fichier est en cours de copie, 2 minutes au plus par vague de copies.
    refetchInterval: (current) => {
      if (!hasPendingAttachment(current.state.data)) {
        pollStartRef.current = null;
        return false;
      }
      if (pollStartRef.current === null) pollStartRef.current = Date.now();
      return Date.now() - pollStartRef.current < PENDING_POLL_MAX_MS ? PENDING_POLL_INTERVAL_MS : false;
    },
  });

  const casier = query.data || null;
  const member = casier?.member || {};
  const memberId = member.id ? String(member.id) : "";

  const flagParams = useMemo(() => ({ discord_id: memberId }), [memberId]);
  const hasPending = hasPendingAttachment(casier);

  // Fin de la fenêtre de sondage avec des copies toujours en attente : on permet de relancer la récupération.
  useEffect(() => {
    setPollExpired(false);
    if (!hasPending) return undefined;
    const start = pollStartRef.current ?? Date.now();
    const remaining = Math.max(0, PENDING_POLL_MAX_MS - (Date.now() - start));
    const timer = setTimeout(() => setPollExpired(true), remaining + 100);
    return () => clearTimeout(timer);
  }, [hasPending, pollEpoch]);

  useEffect(
    () => () => {
      if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    },
    []
  );

  const changeTab = useCallback(
    (next) => {
      if (next && next !== tab) onTabChange?.(next);
    },
    [onTabChange, tab]
  );

  // Une copie relancée ouvre une nouvelle fenêtre de sondage de 2 minutes.
  const restartPolling = useCallback(() => {
    pollStartRef.current = Date.now();
    setPollEpoch((value) => value + 1);
  }, []);

  const copyId = async () => {
    if (!memberId) return;
    const done = await copyText(memberId);
    if (!done) {
      toast.error("Copie impossible : sélectionnez l'ID à la main.");
      return;
    }
    toast.success("ID copié.");
    setCopied(true);
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
  };

  const openAddSanction = useCallback(() => setAddOpen(true), []);
  const openFicheCreate = useCallback(() => setFicheEditor({ fiche: null }), []);
  const openFicheEdit = useCallback((fiche) => {
    if (fiche) setFicheEditor({ fiche });
  }, []);

  const handleSanctionSaved = () => {
    setAddOpen(false);
    changeTab("historique");
  };

  const handleFicheSaved = () => {
    const created = !ficheEditor?.fiche;
    setFicheEditor(null);
    if (created) changeTab("fiches");
  };

  if (query.isPending) return <DetailLoading />;

  if (!casier) {
    const status = query.isError ? errorStatus(query.error) : 404;
    const notFound = status === 404;
    return (
      <div className="cz-detail">
        <div className="cz-card cz-detail-error">
          <div className="cz-empty cz-empty--error" role="alert">
            <ShieldAlert size={26} aria-hidden="true" />
            <h3>{notFound ? "Casier introuvable." : "Impossible de charger ce casier."}</h3>
            <p>
              {notFound
                ? "Ce casier n'existe pas ou plus. Vérifiez le lien, ou choisissez un casier dans la liste."
                : errorMessage(query.error)}
            </p>
            <div className="cz-empty-actions">
              {!notFound && (
                <button type="button" className="cz-button" onClick={() => query.refetch()}>
                  Réessayer
                </button>
              )}
              {onBack && (
                <button type="button" className="cz-button" onClick={onBack}>
                  <ArrowLeft size={16} aria-hidden="true" />
                  Retour à la liste
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const handle = memberHandle(member);
  const sanctions = casier.sanctions || [];
  const fiches = casier.fiches_s || [];
  const activeFiches = fiches.filter((fiche) => fiche.active);
  const activeFichesCount = casier.active_fiches_s_count || activeFiches.length;
  const muteActive = isFuture(casier.active_mute_until);
  const flagsTotal = Number(casier.ai_flags_total) || 0;
  const flagsOpen = Number(casier.ai_flags_open) || 0;
  const creator = creatorLabel(casier.created_by);
  const lastActivity = formatRelative(casier.last_activity_at);
  const titleId = `cz-detail-title-${casier.id}`;

  return (
    <div className="cz-detail">
      <section className="cz-card cz-identity" aria-labelledby={titleId}>
        <div className="cz-identity-main">
          <MemberAvatar member={member} size={64} shape="square" />

          <div className="cz-identity-copy">
            <h2 className="cz-identity-name" id={titleId}>
              {memberName(member)}
            </h2>
            {handle && <p className="cz-identity-handle">{handle}</p>}
            {memberId && (
              <p className="cz-identity-id">
                <span>ID Discord :</span>
                <code className="cz-mono">{memberId}</code>
                <button
                  type="button"
                  className="cz-icon-button cz-icon-button--plain cz-copy"
                  onClick={copyId}
                  aria-label={copied ? "ID Discord copié" : "Copier l'ID Discord"}
                  title={copied ? "ID copié" : "Copier l'ID Discord"}
                >
                  {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
                </button>
              </p>
            )}
          </div>

          <div className="cz-identity-actions">
            <button type="button" className="cz-button cz-button--primary" onClick={openAddSanction}>
              <Plus size={17} aria-hidden="true" />
              Ajouter une sanction
            </button>
            <button type="button" className="cz-button cz-button--fiche" onClick={openFicheCreate}>
              <FilePenLine size={17} aria-hidden="true" />
              Rédiger une fiche S
            </button>
            {SNOWFLAKE.test(memberId) && (
              <Link to={`/moderation/membres/${memberId}`} className="cz-button">
                <Orbit size={17} aria-hidden="true" />
                Vue 360°
              </Link>
            )}
          </div>
        </div>

        <div className="cz-identity-pills">
          <span className="cz-sr-only">Statut :</span>
          <StatusPill status={casier.status || "vierge"} size="lg" title="Statut = sanction la plus grave reçue" />
          {casier.is_prevention && (
            <StatusPill
              variant="prevention"
              title="Casier créé alors que le membre n'était pas sur le serveur Discord"
            />
          )}
          {muteActive && (
            <StatusPill variant="mute" icon={MicOff}>
              Mute en cours · {formatUntil(casier.active_mute_until)}
            </StatusPill>
          )}
          {activeFichesCount > 0 && (
            <button
              type="button"
              className="cz-pill-button"
              onClick={() => changeTab("fiches")}
              aria-label={`${plural(activeFichesCount, "fiche S active", "fiches S actives")} : ouvrir l'onglet Fiches S`}
            >
              <StatusPill variant="fiche" icon={Eye}>
                {plural(activeFichesCount, "fiche S active", "fiches S actives")}
              </StatusPill>
            </button>
          )}
        </div>

        {(casier.created_at || lastActivity) && (
          <p className="cz-identity-meta cz-meta">
            {casier.created_at &&
              `Casier ouvert le ${formatDate(casier.created_at, { withTime: false })}${creator ? ` ${creator}` : ""}`}
            {casier.created_at && lastActivity ? " · " : ""}
            {lastActivity && `Dernière activité ${lastActivity}`}
          </p>
        )}

        {activeFiches.length > 0 && (
          <div className="cz-callout cz-callout--violet cz-fiche-banner">
            <ScrollText size={18} aria-hidden="true" />
            <p>
              Fiche S active : <strong>{activeFiches[0].title || "Sans titre"}</strong>
              {activeFiches.length > 1 ? ` et ${plural(activeFiches.length - 1, "autre")}` : ""}
            </p>
            <button
              type="button"
              className="cz-button cz-button--fiche cz-button--compact"
              onClick={() => changeTab("fiches")}
            >
              <Eye size={15} aria-hidden="true" />
              {activeFiches.length > 1 ? "Voir les fiches" : "Voir la fiche"}
            </button>
          </div>
        )}
      </section>

      <CasierMetrics casier={casier} />

      <Tabs.Root value={tab} onValueChange={changeTab}>
        <Tabs.List className="cz-tabs cz-detail-tablist" aria-label="Sections du casier">
          <Tabs.Trigger value="historique" className="cz-tab">
            Historique
            <TabCount value={sanctions.length} />
          </Tabs.Trigger>
          <Tabs.Trigger value="fiches" className="cz-tab">
            Fiches S
            <TabCount value={fiches.length} />
          </Tabs.Trigger>
          <Tabs.Trigger value="signalements" className="cz-tab">
            Signalements IA
            <TabCount
              value={flagsTotal}
              tone={flagsOpen > 0 ? "open" : "muted"}
              srSuffix={flagsOpen > 0 ? `, dont ${flagsOpen} à traiter` : ""}
            />
          </Tabs.Trigger>
          <Tabs.Trigger value="modifications" className="cz-tab">
            Modifications
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="historique" className="cz-detail-panel">
          <SanctionTimeline
            casier={casier}
            highlightSanctionId={highlightSanctionId}
            onAddSanction={openAddSanction}
            onFilesQueued={restartPolling}
            copyStalled={pollExpired}
          />
        </Tabs.Content>

        <Tabs.Content value="fiches" className="cz-detail-panel">
          <FicheSList casier={casier} onCreate={openFicheCreate} onEdit={openFicheEdit} />
        </Tabs.Content>

        <Tabs.Content value="modifications" className="cz-detail-panel">
          {tab === "modifications" && <HistoryPanel casierId={casier.id} />}
        </Tabs.Content>

        <Tabs.Content value="signalements" className="cz-detail-panel">
          {SNOWFLAKE.test(memberId) ? (
            <AiFlagList
              params={flagParams}
              compact
              highlightFlagId={highlightFlagId}
              onNavigate={onNavigate}
              emptyMessage={FLAGS_EMPTY_MESSAGE}
            />
          ) : (
            <div className="cz-card cz-empty">
              <p>{FLAGS_EMPTY_MESSAGE}</p>
            </div>
          )}
        </Tabs.Content>
      </Tabs.Root>

      <AddSanctionDialog
        open={addOpen}
        casier={casier}
        onClose={() => setAddOpen(false)}
        onSaved={handleSanctionSaved}
      />

      {ficheEditor && (
        <FicheSEditorDialog
          key={ficheEditor.fiche?.id ?? "new"}
          open
          casierId={casier.id}
          casier={casier}
          fiche={ficheEditor.fiche}
          onClose={() => setFicheEditor(null)}
          onSaved={handleFicheSaved}
        />
      )}
    </div>
  );
}
