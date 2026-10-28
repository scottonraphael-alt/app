import "../Handoffs.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

import HandoffCard from "../components/handoffs/HandoffCard";
import HandoffComposer from "../components/handoffs/HandoffComposer";
import {
  PAGE_SIZE,
  STATUS_FILTERS,
  createHandoff,
  deleteHandoff,
  errorMessage,
  fetchHandoffs,
  handoffKeys,
  markHandoffRead,
  resolveHandoff,
  updateHandoff,
} from "../components/handoffs/handoffsApi";

const LIST_KEY = ["handoffs", "list"];

function mapPages(data, fn) {
  if (!data?.pages) return data;
  return { ...data, pages: data.pages.map((page) => fn(page)) };
}

export default function HandoffsPage({ isResponsable = false, currentHelperId, helper }) {
  const me = currentHelperId || helper?.id;
  const qc = useQueryClient();
  const [status, setStatus] = useState("open");
  const [createError, setCreateError] = useState("");
  const [editError, setEditError] = useState("");
  const readSent = useRef(new Set());
  const composerRef = useRef(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // Raccourci « n » : /staff/passation?nouveau=1 met le focus dans la saisie puis retire le paramètre.
  useEffect(() => {
    if (searchParams.get("nouveau") !== "1") return;
    composerRef.current?.focus();
    const next = new URLSearchParams(searchParams);
    next.delete("nouveau");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // Page sans barre latérale, comme le casier.
  useEffect(() => {
    document.body.classList.add("handoffs-no-nav");
    return () => document.body.classList.remove("handoffs-no-nav");
  }, []);

  const query = useInfiniteQuery({
    queryKey: handoffKeys.list(status),
    initialPageParam: undefined,
    queryFn: ({ pageParam }) => fetchHandoffs({ status, before: pageParam }),
    getNextPageParam: (last) =>
      last.items.length >= PAGE_SIZE ? last.items[last.items.length - 1].id : undefined,
  });

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const unread = query.data?.pages[0]?.unread_count ?? 0;

  const patchAll = useCallback((id, fn) => {
    qc.setQueriesData({ queryKey: LIST_KEY }, (data) =>
      mapPages(data, (page) => ({
        ...page,
        items: page.items.flatMap((it) => (it.id === id ? [].concat(fn(it) ?? []) : [it])),
      })));
  }, [qc]);

  const snapshot = () => qc.getQueriesData({ queryKey: LIST_KEY });
  const restore = (snap) => snap?.forEach(([key, data]) => qc.setQueryData(key, data));
  const refresh = () => qc.invalidateQueries({ queryKey: LIST_KEY });

  const create = useMutation({
    mutationFn: createHandoff,
    onSuccess: () => { setCreateError(""); toast.success("Transmission publiée."); refresh(); },
    onError: (err) => setCreateError(errorMessage(err)),
  });

  const edit = useMutation({
    mutationFn: ({ id, payload }) => updateHandoff(id, payload),
    onMutate: async ({ id, payload }) => {
      await qc.cancelQueries({ queryKey: LIST_KEY });
      const snap = snapshot();
      patchAll(id, (it) => ({ ...it, ...payload }));
      return { snap };
    },
    onError: (err, _v, ctx) => { restore(ctx?.snap); setEditError(errorMessage(err)); toast.error(errorMessage(err)); },
    onSuccess: () => setEditError(""),
    onSettled: refresh,
  });

  const resolve = useMutation({
    mutationFn: ({ id, resolved }) => resolveHandoff(id, resolved),
    onMutate: async ({ id, resolved }) => {
      await qc.cancelQueries({ queryKey: LIST_KEY });
      const snap = snapshot();
      patchAll(id, (it) =>
        status !== "all" && resolved !== (status === "resolved") ? null : { ...it, resolved });
      return { snap };
    },
    onError: (err, _v, ctx) => { restore(ctx?.snap); toast.error(errorMessage(err)); },
    onSettled: refresh,
  });

  const remove = useMutation({
    mutationFn: ({ id }) => deleteHandoff(id),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: LIST_KEY });
      const snap = snapshot();
      patchAll(id, () => null);
      return { snap };
    },
    onSuccess: () => toast.success("Transmission supprimée."),
    onError: (err, _v, ctx) => { restore(ctx?.snap); toast.error(errorMessage(err)); },
    onSettled: refresh,
  });

  const markRead = useMutation({
    mutationFn: markHandoffRead,
    onMutate: (id) => {
      patchAll(id, (it) => ({ ...it, read: true }));
      qc.setQueriesData({ queryKey: LIST_KEY }, (data) =>
        mapPages(data, (page) => ({ ...page, unread_count: Math.max(0, (page.unread_count || 0) - 1) })));
    },
    onSuccess: (res) => {
      if (typeof res?.unread_count === "number") {
        qc.setQueriesData({ queryKey: LIST_KEY }, (data) =>
          mapPages(data, (page) => ({ ...page, unread_count: res.unread_count })));
      }
    },
    onError: (_e, id) => { readSent.current.delete(id); },
  });

  const onRead = useCallback((id) => {
    if (readSent.current.has(id)) return;
    readSent.current.add(id);
    markRead.mutate(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSave = (id, payload, done) => {
    setEditError("");
    edit.mutate({ id, payload }, { onSuccess: done });
  };

  return (
    <section className="ho-page" data-testid="handoffs-page">
      <header className="ho-header">
        <div className="ho-header-copy">
          <p className="ho-eyebrow">ESPACE STAFF · PASSATION</p>
          <h1>Cahier de passation</h1>
          <p className="ho-intro">
            Les informations à transmettre à l'équipe suivante.
            {unread > 0 && <strong className="ho-unread-pill"> {unread} non lue{unread > 1 ? "s" : ""}</strong>}
          </p>
        </div>
        <div className="ho-header-actions">
          <Link to="/" className="ho-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <div className="ho-layout">
        <aside className="ho-panel ho-compose-panel">
          <h2>Nouvelle transmission</h2>
          <HandoffComposer
            textareaRef={composerRef}
            busy={create.isPending}
            error={createError}
            onSubmit={(payload) => { setCreateError(""); create.mutate(payload); }}
          />
        </aside>

        <div className="ho-feed">
          <div className="ho-toolbar" role="tablist" aria-label="Filtrer les transmissions">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                role="tab"
                aria-selected={status === f.value}
                className={`ho-filter${status === f.value ? " is-on" : ""}`}
                onClick={() => setStatus(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {query.isLoading && <p className="ho-state" role="status">Chargement…</p>}
          {query.isError && (
            <div className="ho-state ho-state--error" role="alert">
              {errorMessage(query.error)}{" "}
              <button type="button" className="ho-btn" onClick={() => query.refetch()}>Réessayer</button>
            </div>
          )}
          {!query.isLoading && !query.isError && items.length === 0 && (
            <p className="ho-state">Aucune transmission {status === "resolved" ? "résolue" : status === "open" ? "ouverte" : ""} pour le moment.</p>
          )}

          <ul className="ho-list" aria-live="polite">
            {items.map((item) => (
              <HandoffCard
                key={item.id}
                item={item}
                canManage={isResponsable || (me && item.author_id === me)}
                onRead={onRead}
                onResolve={(it) => resolve.mutate({ id: it.id, resolved: !it.resolved })}
                onPin={(it) => edit.mutate({ id: it.id, payload: { pinned: !it.pinned } })}
                onSave={onSave}
                onDelete={(it) => remove.mutate({ id: it.id })}
                saving={edit.isPending}
                saveError={editError}
              />
            ))}
          </ul>

          {query.hasNextPage && (
            <button
              type="button"
              className="ho-btn ho-more"
              disabled={query.isFetchingNextPage}
              onClick={() => query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? "Chargement…" : "Charger plus"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
