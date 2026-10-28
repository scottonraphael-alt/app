import "../Casier.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Check, Gavel, ThumbsDown } from "lucide-react";

import { casierKeys, errorMessage, listAiFlags, reviewAiFlag } from "../components/casier/casierApi";
import { formatRelative, formatVerdict, casierLink, memberName } from "../components/casier/formatters";

const PARAMS = { review_status: "a_traiter", limit: 100 };
const LINKED_MSG = "Ce signalement est lié à une sanction : il ne peut pas être classé faux positif.";

function typingTarget(target) {
  const tag = target?.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable;
}

export default function AiReviewQueuePage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [done, setDone] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const cardRef = useRef(null);

  useEffect(() => {
    document.body.classList.add("casier-no-nav");
    return () => document.body.classList.remove("casier-no-nav");
  }, []);

  const query = useQuery({
    queryKey: casierKeys.aiFlagList(PARAMS),
    queryFn: ({ signal }) => listAiFlags(PARAMS, { signal }),
    retry: false,
  });
  const items = useMemo(() => (query.data?.items || []).filter((f) => !done.has(f.id)), [query.data, done]);
  const current = items[Math.min(index, Math.max(0, items.length - 1))] || null;

  useEffect(() => {
    if (index > 0 && index >= items.length) setIndex(Math.max(0, items.length - 1));
  }, [index, items.length]);

  const review = useCallback(
    async (flag, status) => {
      if (!flag || busyRef.current) return;
      if (status === "faux_positif" && flag.sanction) {
        toast.error(LINKED_MSG);
        return;
      }
      busyRef.current = true;
      setBusy(true);
      try {
        await reviewAiFlag(flag.id, { review_status: status });
        setDone((prev) => new Set(prev).add(flag.id));
        toast.success(status === "pertinent" ? "Signalement validé." : "Classé faux positif.", {
          duration: 6000,
          action: {
            label: "Annuler",
            onClick: () =>
              reviewAiFlag(flag.id, { review_status: "a_traiter" })
                .then(() => {
                  setDone((prev) => {
                    const next = new Set(prev);
                    next.delete(flag.id);
                    return next;
                  });
                  queryClient.invalidateQueries({ queryKey: casierKeys.aiFlags() });
                })
                .catch((error) => toast.error(errorMessage(error))),
          },
        });
        queryClient.invalidateQueries({ queryKey: casierKeys.lists() });
      } catch (error) {
        toast.error(errorMessage(error));
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [queryClient]
  );

  const sanction = useCallback(
    (flag) => {
      if (!flag) return;
      navigate(
        flag.casier_id
          ? casierLink({ casierId: flag.casier_id, onglet: "signalements", signalementId: flag.id })
          : casierLink({ vue: "signalements", signalementId: flag.id })
      );
    },
    [navigate]
  );

  useEffect(() => {
    const onKey = (event) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || typingTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "j") setIndex((i) => Math.min(i + 1, Math.max(0, items.length - 1)));
      else if (key === "k") setIndex((i) => Math.max(0, i - 1));
      else if (key === "v") review(current, "pertinent");
      else if (key === "f") review(current, "faux_positif");
      else if (key === "s") sanction(current);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items.length, current, review, sanction]);

  useEffect(() => {
    cardRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [current?.id]);

  const author = current?.author || { id: current?.discord_id };
  const verdict = current?.verdict;

  return (
    <section className="cz-page" data-testid="ai-review-queue-page">
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE OPÉRATEUR · MODÉRATION</p>
          <h1>Revue rapide des signalements IA</h1>
          <p className="cz-intro">
            {items.length > 0 ? `${items.length} à traiter.` : "Rien à traiter pour le moment."}
          </p>
        </div>
        <div className="cz-header-actions">
          <Link to="/" className="cz-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <p className="cz-rq-keys" aria-label="Raccourcis clavier">
        <kbd>J</kbd> suivant · <kbd>K</kbd> précédent · <kbd>V</kbd> valider · <kbd>F</kbd> faux positif · <kbd>S</kbd> sanctionner
      </p>

      {query.isLoading && <p className="cz-meta" role="status">Chargement…</p>}
      {query.isError && <p className="cz-empty cz-empty--error" role="alert">{errorMessage(query.error)}</p>}
      {query.isSuccess && items.length === 0 && (
        <div className="cz-empty"><h3>File vide.</h3><p>Tous les signalements ont été revus.</p></div>
      )}

      {items.length > 0 && (
        <div className="cz-rq-layout">
          <ul className="cz-rq-list" aria-label="File des signalements">
            {items.map((flag, i) => (
              <li key={flag.id}>
                <button
                  type="button"
                  ref={flag.id === current?.id ? cardRef : null}
                  className="cz-rq-item"
                  aria-current={flag.id === current?.id ? "true" : undefined}
                  onClick={() => setIndex(i)}
                >
                  <strong>{memberName(flag.author || { id: flag.discord_id })}</strong>
                  <span>{formatRelative(flag.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>

          {current && (
            <article className="cz-card cz-rq-card" aria-live="polite">
              <h2>{memberName(author)}</h2>
              <p className="cz-meta">
                {current.channel?.name ? `#${current.channel.name} · ` : ""}
                {formatRelative(current.created_at)}
              </p>
              <blockquote className="cz-flag-text">{current.message?.content || "Message non disponible."}</blockquote>
              {verdict && <p className="cz-rq-verdict">{formatVerdict(verdict)}</p>}
              <div className="cz-rq-actions">
                <button type="button" className="cz-button cz-button--primary" disabled={busy} onClick={() => review(current, "pertinent")}>
                  <Check size={16} aria-hidden="true" /> Valider <kbd>V</kbd>
                </button>
                <button type="button" className="cz-button" disabled={busy} onClick={() => review(current, "faux_positif")}>
                  <ThumbsDown size={16} aria-hidden="true" /> Faux positif <kbd>F</kbd>
                </button>
                <button type="button" className="cz-button cz-button--danger" disabled={busy} onClick={() => sanction(current)}>
                  <Gavel size={16} aria-hidden="true" /> Sanctionner <kbd>S</kbd>
                </button>
              </div>
            </article>
          )}
        </div>
      )}
    </section>
  );
}
