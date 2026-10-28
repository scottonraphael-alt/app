import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Bell,
  CheckCheck,
  LoaderCircle,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import "../Notifications.css";

const PAGE_SIZE = 30;

const TYPE_OPTIONS = [
  { value: "", label: "Tous les types" },
  { value: "ticket_assigned", label: "Suivi attribué" },
  { value: "ticket_crisis", label: "Crise sur un ticket" },
  { value: "ticket_sla", label: "Délai de réponse" },
  { value: "task_assigned", label: "Tâche attribuée" },
  { value: "task_due", label: "Tâche à rendre" },
  { value: "action_assigned", label: "Action de réunion" },
  { value: "action_due", label: "Action à rendre" },
  { value: "mention", label: "Mention" },
  { value: "handoff_urgent", label: "Passation urgente" },
  { value: "staff_load", label: "Point d’équipe" },
  { value: "monthly_report", label: "Rapport mensuel" },
];

const TYPE_LABELS = Object.fromEntries(
  TYPE_OPTIONS.filter((option) => option.value).map((option) => [option.value, option.label]),
);

const formatDate = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const [items, setItems] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [nextBefore, setNextBefore] = useState(null);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [type, setType] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const requestRef = useRef(0);

  useEffect(() => {
    document.body.classList.add("notif-no-nav");
    return () => document.body.classList.remove("notif-no-nav");
  }, []);

  const refreshBell = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    [queryClient],
  );

  const buildParams = useCallback(
    (before) => {
      const params = { limit: PAGE_SIZE };
      if (onlyUnread) params.unread = "1";
      if (type) params.type = type;
      if (before) params.before = before;
      return params;
    },
    [onlyUnread, type],
  );

  useEffect(() => {
    const token = ++requestRef.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");

    api
      .get("/notifications", { params: buildParams(null), signal: controller.signal })
      .then((response) => {
        if (token !== requestRef.current) return;
        const data = response.data;
        setItems(data.items || []);
        setUnreadCount(data.unread_count || 0);
        setHasMore(Boolean(data.has_more));
        setNextBefore(data.next_before || null);
      })
      .catch((err) => {
        if (controller.signal.aborted || token !== requestRef.current) return;
        setError(getErrorMessage(err));
      })
      .finally(() => {
        if (token === requestRef.current) setLoading(false);
      });

    return () => controller.abort();
  }, [buildParams, reloadKey]);

  const loadMore = async () => {
    if (!nextBefore || loadingMore) return;
    const token = requestRef.current;
    setLoadingMore(true);
    try {
      const response = await api.get("/notifications", { params: buildParams(nextBefore) });
      if (token !== requestRef.current) return;
      const data = response.data;
      setItems((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...(data.items || []).filter((item) => !known.has(item.id))];
      });
      setUnreadCount(data.unread_count || 0);
      setHasMore(Boolean(data.has_more));
      setNextBefore(data.next_before || null);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

  const markRead = async (item) => {
    if (item.read_at) return;
    const readAt = new Date().toISOString();
    setItems((current) =>
      onlyUnread
        ? current.filter((entry) => entry.id !== item.id)
        : current.map((entry) => (entry.id === item.id ? { ...entry, read_at: readAt } : entry)),
    );
    setUnreadCount((count) => Math.max(0, count - 1));
    try {
      await api.post(`/notifications/${item.id}/read`);
    } catch (err) {
      toast.error(getErrorMessage(err));
      setReloadKey((value) => value + 1);
    } finally {
      refreshBell();
    }
  };

  const markAllRead = async () => {
    if (busy || !unreadCount) return;
    setBusy(true);
    try {
      await api.post("/notifications/read-all");
      toast.success("Tout est marqué comme lu.");
      setReloadKey((value) => value + 1);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
      refreshBell();
    }
  };

  const removeOne = async (item) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.delete(`/notifications/${item.id}`);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      if (!item.read_at) setUnreadCount((count) => Math.max(0, count - 1));
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
      refreshBell();
    }
  };

  const clearRead = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const response = await api.post("/notifications/clear-read");
      const deleted = response.data?.deleted ?? 0;
      toast.success(
        deleted
          ? `${deleted} notification${deleted > 1 ? "s lues supprimées" : " lue supprimée"}.`
          : "Aucune notification lue à supprimer.",
      );
      setConfirmClear(false);
      setReloadKey((value) => value + 1);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
      refreshBell();
    }
  };

  return (
    <section className="nt-page" data-testid="notifications-page">
      <header className="nt-header">
        <div className="nt-header-copy">
          <p className="nt-eyebrow">ESPACE PERSONNEL</p>
          <h1>Notifications</h1>
          <p className="nt-intro">
            Tout ce qui vous concerne : attributions, échéances, alertes et rappels.
          </p>
        </div>

        <Link to="/" className="nt-home">
          Accueil
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </header>

      <div className="nt-toolbar" role="group" aria-label="Filtres et actions">
        <div className="nt-filters">
          <button
            type="button"
            className={`nt-chip ${onlyUnread ? "is-active" : ""}`}
            aria-pressed={onlyUnread}
            onClick={() => setOnlyUnread((value) => !value)}
            data-testid="notifications-unread-filter"
          >
            Non lues{unreadCount ? ` (${unreadCount})` : ""}
          </button>

          <label className="nt-select-label">
            <span className="nt-sr">Filtrer par type</span>
            <select
              className="nt-select"
              value={type}
              onChange={(event) => setType(event.target.value)}
              data-testid="notifications-type-filter"
            >
              {TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="nt-actions">
          <button
            type="button"
            className="nt-button"
            onClick={markAllRead}
            disabled={busy || !unreadCount}
            data-testid="notifications-read-all"
          >
            <CheckCheck size={16} aria-hidden="true" />
            Tout marquer comme lu
          </button>

          {confirmClear ? (
            <span className="nt-confirm" role="group" aria-label="Confirmer la suppression des notifications lues">
              <span>Supprimer les lues ?</span>
              <button type="button" className="nt-button nt-button--danger" onClick={clearRead} disabled={busy}>
                Oui, supprimer
              </button>
              <button type="button" className="nt-button" onClick={() => setConfirmClear(false)} disabled={busy}>
                Annuler
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="nt-button"
              onClick={() => setConfirmClear(true)}
              disabled={busy}
              data-testid="notifications-clear-read"
            >
              <Trash2 size={16} aria-hidden="true" />
              Effacer les lues
            </button>
          )}
        </div>
      </div>

      <div className="nt-list-card" aria-busy={loading}>
        {loading ? (
          <div className="nt-state" role="status">
            <LoaderCircle className="nt-spin" size={22} aria-hidden="true" />
            Chargement des notifications…
          </div>
        ) : error ? (
          <div className="nt-error" role="alert">
            <h2>Les notifications n’ont pas pu être chargées.</h2>
            <p>{error}</p>
            <button type="button" className="nt-button" onClick={() => setReloadKey((value) => value + 1)}>
              Réessayer
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="nt-state nt-empty">
            <Bell size={26} aria-hidden="true" />
            <p>
              {onlyUnread || type
                ? "Aucune notification ne correspond à ces filtres."
                : "Rien de nouveau pour le moment."}
            </p>
          </div>
        ) : (
          <ul className="nt-list">
            {items.map((item) => {
              const unread = !item.read_at;
              const content = (
                <>
                  <span className="nt-item-top">
                    <span className="nt-type">{TYPE_LABELS[item.type] || "Notification"}</span>
                    <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
                  </span>
                  <span className="nt-title">{item.title}</span>
                  {item.body && <span className="nt-body">{item.body}</span>}
                  {item.link && (
                    <span className="nt-link-hint">
                      Ouvrir <ArrowRight size={14} aria-hidden="true" />
                    </span>
                  )}
                </>
              );

              return (
                <li key={item.id} className={`nt-item ${unread ? "is-unread" : ""}`}>
                  {unread && <span className="nt-dot" aria-hidden="true" />}

                  {item.link ? (
                    <Link to={item.link} className="nt-item-main" onClick={() => markRead(item)}>
                      {content}
                    </Link>
                  ) : (
                    <div className="nt-item-main">{content}</div>
                  )}

                  <div className="nt-item-actions">
                    {unread && (
                      <button
                        type="button"
                        className="nt-icon-button"
                        onClick={() => markRead(item)}
                        aria-label={`Marquer comme lue : ${item.title}`}
                        title="Marquer comme lue"
                      >
                        <CheckCheck size={17} aria-hidden="true" />
                      </button>
                    )}
                    <button
                      type="button"
                      className="nt-icon-button"
                      onClick={() => removeOne(item)}
                      disabled={busy}
                      aria-label={`Supprimer : ${item.title}`}
                      title="Supprimer"
                    >
                      <Trash2 size={17} aria-hidden="true" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {!loading && !error && hasMore && (
          <div className="nt-more">
            <button type="button" className="nt-button" onClick={loadMore} disabled={loadingMore}>
              {loadingMore && <LoaderCircle className="nt-spin" size={16} aria-hidden="true" />}
              {loadingMore ? "Chargement…" : "Voir plus"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
