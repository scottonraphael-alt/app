// Importé en premier : les CSS des composants enfants viennent après et peuvent surcharger.
import "../Casier.css";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import * as Tabs from "@radix-ui/react-tabs";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BarChart3, Bot, CheckSquare, Keyboard, MousePointerClick, ShieldCheck } from "lucide-react";

import CreateCasierModal from "../components/CreateCasierModal";
import AiFlagsView from "../components/casier/AiFlagsView";
import CasierBulkBar from "../components/casier/CasierBulkBar";
import CasierDetail from "../components/casier/CasierDetail";
import CasierList from "../components/casier/CasierList";
import CasierSearchBar from "../components/casier/CasierSearchBar";
import { casierKeys, errorMessage, listAiFlags, listCasiers } from "../components/casier/casierApi";
import {
  CASIER_VIEWS,
  DEFAULT_DETAIL_TAB,
  DEFAULT_SCOPE,
  DEFAULT_SORT,
  DEFAULT_VIEW,
  DETAIL_TABS,
  SEARCH_DEBOUNCE_MS,
  SEARCH_MAX_LENGTH,
  SEARCH_MAX_TERMS,
  STATUS_ORDER,
} from "../components/casier/casierConstants";
import { plural } from "../components/casier/formatters";

const VIEWS = Object.values(CASIER_VIEWS);
const URL_KEYS = ["vue", "casier", "onglet", "sanction", "signalement"];
const URL_DEFAULTS = { vue: DEFAULT_VIEW, onglet: DEFAULT_DETAIL_TAB };
const ID_PATTERN = /^[0-9a-f]{24}$/;
const WIDE_QUERY = "(min-width: 900px)";
const FLAGS_COUNT_PARAMS = { limit: 1 };
const FLAGS_COUNT_REFRESH_MS = 120_000;

const DEFAULT_FILTERS = {
  q: "",
  scope: DEFAULT_SCOPE,
  status: [],
  has_active_fiche_s: false,
  prevention: false,
  has_open_ai_flags: false,
  sort: DEFAULT_SORT,
};

function validId(value) {
  return value && ID_PATTERN.test(value) ? value : null;
}

function splitTerms(text) {
  return String(text || "").split(/\s+/).filter(Boolean);
}

// Pas de nouvel essai sur une erreur 4xx (422 de la recherche, 404…).
function retryServerErrors(failureCount, error) {
  const status = error?.response?.status;
  if (status && status < 500) return false;
  return failureCount < 2;
}

function readMedia(query) {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query).matches
    : true;
}

function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => readMedia(query));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    if (media.addEventListener) {
      media.addEventListener("change", update);
      return () => media.removeEventListener("change", update);
    }
    media.addListener(update);
    return () => media.removeListener(update);
  }, [query]);

  return matches;
}

function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

function DetailSkeleton() {
  return (
    <div className="cz-card cz-skeleton-card" aria-hidden="true">
      <div className="cz-skeleton-row cz-skeleton-row--flush">
        <span className="cz-skeleton cz-skeleton--avatar" />
        <div className="cz-skeleton-stack">
          <span className="cz-skeleton cz-skeleton--title" />
          <span className="cz-skeleton cz-skeleton--short" />
        </div>
      </div>
      <span className="cz-skeleton cz-skeleton--block" />
      <span className="cz-skeleton cz-skeleton--block" />
      <span className="cz-skeleton cz-skeleton--block" />
    </div>
  );
}

export default function ModerationCasierPage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const routerNavigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isWide = useMediaQuery(WIDE_QUERY);

  const casierParam = validId(searchParams.get("casier"));
  const sanctionParam = validId(searchParams.get("sanction"));
  const signalementParam = validId(searchParams.get("signalement"));
  const ongletParam = searchParams.get("onglet");
  const vueParam = searchParams.get("vue");
  // Un signalement sans casier ni vue (lien des logs) s'ouvre dans la liste globale.
  const vue = VIEWS.includes(vueParam)
    ? vueParam
    : signalementParam && !casierParam
      ? CASIER_VIEWS.signalements
      : DEFAULT_VIEW;
  const detailTab = DETAIL_TABS.includes(ongletParam)
    ? ongletParam
    : signalementParam
      ? "signalements"
      : DEFAULT_DETAIL_TAB;

  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [createOpen, setCreateOpen] = useState(false);
  const [bulkMode, setBulkMode] = useState(false);
  const [checked, setChecked] = useState(() => new Set());
  const [visited, setVisited] = useState(() => ({ [vue]: true }));
  const seen = visited[vue] ? visited : { ...visited, [vue]: true };

  const layoutRef = useRef(null);
  const listScrollRef = useRef(null);
  const previousCasierRef = useRef(casierParam);
  const locationStateRef = useRef(location.state);
  locationStateRef.current = location.state;

  useEffect(() => {
    document.body.classList.add("casier-no-nav");

    return () => {
      document.body.classList.remove("casier-no-nav");
    };
  }, []);

  // Une vue déjà ouverte reste montée (cachée) : filtres et défilement conservés.
  useEffect(() => {
    setVisited((current) => (current[vue] ? current : { ...current, [vue]: true }));
  }, [vue]);

  // Écrit les paramètres d'URL ; les valeurs vides ou par défaut sont retirées.
  const writeParams = useCallback(
    (patch, { replace = true, reset = false, state } = {}) => {
      setSearchParams(
        (current) => {
          const next = reset ? new URLSearchParams() : new URLSearchParams(current);
          Object.entries(patch).forEach(([key, value]) => {
            if (value === undefined || value === null || value === "" || URL_DEFAULTS[key] === value) {
              next.delete(key);
            } else {
              next.set(key, String(value));
            }
          });
          return next;
        },
        { replace, state: state !== undefined ? state : replace ? locationStateRef.current : null }
      );
    },
    [setSearchParams]
  );

  // Lien profond interne : remplace toute la requête et crée une entrée d'historique.
  const navigate = useCallback(
    (params = {}, options = {}) => {
      const patch = {};
      URL_KEYS.forEach((key) => {
        patch[key] = params?.[key];
      });
      writeParams(patch, { replace: false, reset: true, ...options });
    },
    [writeParams]
  );

  /* Recherche et filtres */

  const typedQuery = filters.q.trim().slice(0, SEARCH_MAX_LENGTH);
  const debouncedQuery = useDebouncedValue(typedQuery, SEARCH_DEBOUNCE_MS);
  // Effacer la recherche agit tout de suite ; la saisie attend l'anti-rebond.
  const searchQuery = typedQuery ? splitTerms(debouncedQuery).slice(0, SEARCH_MAX_TERMS).join(" ") : "";
  const searchNotice =
    splitTerms(typedQuery).length > SEARCH_MAX_TERMS
      ? `${SEARCH_MAX_TERMS} mots maximum : seuls les ${SEARCH_MAX_TERMS} premiers sont utilisés.`
      : null;

  const statusFilter = useMemo(
    () => STATUS_ORDER.filter((value) => (filters.status || []).includes(value)),
    [filters.status]
  );

  // Bascules : activée → true ; désactivée → paramètre absent (jamais false).
  const listParams = useMemo(() => {
    const params = { sort: filters.sort };
    if (searchQuery) {
      params.q = searchQuery;
      params.scope = filters.scope;
    }
    if (statusFilter.length) params.status = statusFilter;
    if (filters.has_active_fiche_s) params.has_active_fiche_s = true;
    if (filters.prevention) params.prevention = true;
    if (filters.has_open_ai_flags) params.has_open_ai_flags = true;
    return params;
  }, [
    searchQuery,
    statusFilter,
    filters.scope,
    filters.sort,
    filters.has_active_fiche_s,
    filters.prevention,
    filters.has_open_ai_flags,
  ]);

  const resultsKey = useMemo(() => JSON.stringify(listParams), [listParams]);

  const isFiltered = Boolean(
    searchQuery ||
      statusFilter.length ||
      filters.has_active_fiche_s ||
      filters.prevention ||
      filters.has_open_ai_flags
  );

  const canReset = Boolean(
    typedQuery ||
      statusFilter.length ||
      filters.has_active_fiche_s ||
      filters.prevention ||
      filters.has_open_ai_flags ||
      filters.scope !== DEFAULT_FILTERS.scope ||
      filters.sort !== DEFAULT_FILTERS.sort
  );

  const changeFilters = useCallback((patch) => {
    setFilters((current) => ({ ...current, ...(patch || {}) }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
  }, []);

  /* Données */

  const casiersQuery = useQuery({
    queryKey: casierKeys.list(listParams),
    queryFn: ({ signal }) =>
      listCasiers(
        {
          ...listParams,
          ...(listParams.status ? { status: [...listParams.status] } : {}),
        },
        { signal }
      ),
    placeholderData: keepPreviousData,
    enabled: Boolean(seen.casiers),
    retry: retryServerErrors,
  });

  const flagsCountQuery = useQuery({
    queryKey: casierKeys.aiFlagList(FLAGS_COUNT_PARAMS),
    queryFn: ({ signal }) => listAiFlags({ ...FLAGS_COUNT_PARAMS }, { signal }),
    refetchInterval: FLAGS_COUNT_REFRESH_MS,
    retry: retryServerErrors,
  });

  const casiers = useMemo(
    () => (Array.isArray(casiersQuery.data) ? casiersQuery.data : []),
    [casiersQuery.data]
  );
  const firstCasierId = casiers[0]?.id || null;
  const listLoading = Boolean(seen.casiers) && casiersQuery.isPending;
  const listError = casiersQuery.isError && !casiersQuery.data ? errorMessage(casiersQuery.error) : null;
  const openFlags = Number(flagsCountQuery.data?.counts?.a_traiter) || 0;
  const effectiveCasierId = casierParam || (isWide ? firstCasierId : null);

  const countLabel =
    casiersQuery.isSuccess && !casiersQuery.isPlaceholderData
      ? isFiltered
        ? `${plural(casiers.length, "casier", "casiers")} ${casiers.length > 1 ? "trouvés" : "trouvé"}`
        : plural(casiers.length, "casier", "casiers")
      : "";

  // Grand écran sans casier dans l'URL : le premier de la liste est sélectionné (et fixé dans l'URL).
  useEffect(() => {
    if (vue !== CASIER_VIEWS.casiers || !isWide || casierParam || !firstCasierId) return;
    if (casiersQuery.isPlaceholderData) return;
    writeParams({ casier: firstCasierId }, { replace: true });
  }, [vue, isWide, casierParam, firstCasierId, casiersQuery.isPlaceholderData, writeParams]);

  // Changement de casier : on remonte en haut du détail ; retour à la liste : on retrouve sa position.
  useLayoutEffect(() => {
    const previous = previousCasierRef.current;
    previousCasierRef.current = casierParam;
    if (previous === casierParam) return;

    if (!casierParam) {
      if (!isWide && listScrollRef.current !== null) window.scrollTo(0, listScrollRef.current);
      listScrollRef.current = null;
      return;
    }

    const layout = layoutRef.current;
    if (!layout) return;
    const top = layout.getBoundingClientRect().top + window.scrollY - 16;
    if (window.scrollY > top) window.scrollTo(0, Math.max(0, top));
  }, [casierParam, isWide]);

  /* Actions */

  const selectCasier = useCallback(
    (casierId) => {
      if (!validId(casierId)) return;
      if (casierId === casierParam && !ongletParam && !sanctionParam && !signalementParam) return;
      if (!isWide) listScrollRef.current = window.scrollY;
      navigate({ casier: casierId }, { state: { czFromList: true } });
    },
    [casierParam, ongletParam, sanctionParam, signalementParam, isWide, navigate]
  );

  const backToList = useCallback(() => {
    if (location.state?.czFromList) {
      routerNavigate(-1);
      return;
    }
    writeParams({ casier: null, onglet: null, sanction: null, signalement: null }, { replace: true, state: null });
  }, [location.state, routerNavigate, writeParams]);

  const changeView = useCallback(
    (next) => {
      if (!VIEWS.includes(next)) return;
      writeParams({ vue: next, sanction: null, signalement: null }, { replace: true });
    },
    [writeParams]
  );

  const changeDetailTab = useCallback(
    (tab) => {
      writeParams(
        {
          casier: effectiveCasierId,
          onglet: DETAIL_TABS.includes(tab) ? tab : null,
          sanction: null,
          signalement: null,
        },
        { replace: true }
      );
    },
    [effectiveCasierId, writeParams]
  );

  const toggleChecked = useCallback((id) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else if (next.size < 100) next.add(id);
      return next;
    });
  }, []);
  const checkAll = useCallback(
    () => setChecked(new Set(casiers.slice(0, 100).map((item) => item.id))),
    [casiers]
  );
  const closeBulk = useCallback(() => {
    setBulkMode(false);
    setChecked(new Set());
  }, []);

  const openCreate = useCallback(() => setCreateOpen(true), []);
  const closeCreate = useCallback(() => setCreateOpen(false), []);

  // Création réussie (ou casier existant retrouvé après un 409) : on ouvre le casier.
  const handleCreated = useCallback(
    (created) => {
      const casierId = typeof created === "string" ? created : created?.id;
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: casierKeys.lists() });
      if (validId(casierId)) navigate({ casier: casierId });
    },
    [navigate, queryClient]
  );

  return (
    <section className="cz-page" data-testid="moderation-casier-page">
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE OPÉRATEUR · MODÉRATION</p>
          <h1>Casiers</h1>
          <p className="cz-intro">
            L'historique de modération de chaque membre : sanctions, fiches S et signalements de l'IA.
          </p>
        </div>

        <div className="cz-header-actions">
          <Link to="/" className="cz-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>

          <Link to="/moderation/revue-ia" className="cz-button">
            <Keyboard size={17} aria-hidden="true" />
            Revue rapide
          </Link>

          <Link to="/moderation/statistiques" className="cz-button">
            <BarChart3 size={17} aria-hidden="true" />
            Statistiques
          </Link>

          <button
            type="button"
            className="cz-button cz-button--primary"
            onClick={openCreate}
            data-testid="create-casier-button"
          >
            <ShieldCheck size={17} aria-hidden="true" />
            Créer un casier
          </button>
        </div>
      </header>

      <Tabs.Root value={vue} onValueChange={changeView}>
        <Tabs.List className="cz-tabs cz-tabs--view" aria-label="Vues de la modération">
          <Tabs.Trigger value={CASIER_VIEWS.casiers} className="cz-tab">
            <ShieldCheck size={16} aria-hidden="true" />
            Casiers
          </Tabs.Trigger>

          <Tabs.Trigger value={CASIER_VIEWS.signalements} className="cz-tab">
            <Bot size={16} aria-hidden="true" />
            Signalements IA
            {openFlags > 0 && (
              <span className="cz-tab-count">
                {openFlags}
                <span className="cz-sr-only"> à traiter</span>
              </span>
            )}
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content
          value={CASIER_VIEWS.casiers}
          forceMount
          hidden={vue !== CASIER_VIEWS.casiers}
          className="cz-view"
        >
          {seen.casiers && (
            <div ref={layoutRef} className={`cz-layout${casierParam ? " has-selection" : ""}`}>
              <div className="cz-list-col">
                <section className="cz-panel" aria-labelledby="cz-list-title">
                  <header className="cz-panel-header cz-panel-header--red">
                    <span className="cz-panel-icon" aria-hidden="true">
                      <ShieldCheck size={23} />
                    </span>

                    <div className="cz-panel-heading">
                      <h2 id="cz-list-title">Dossiers de modération</h2>
                      <p>Statut = sanction la plus grave reçue.</p>
                    </div>

                    <span className="cz-count-live" role="status" aria-live="polite">
                      {countLabel && <span className="cz-count">{countLabel}</span>}
                    </span>
                  </header>

                  <div className="cz-panel-toolbar">
                    <CasierSearchBar
                      filters={filters}
                      onChange={changeFilters}
                      onReset={resetFilters}
                      canReset={canReset}
                      notice={searchNotice}
                      busy={Boolean(typedQuery) && casiersQuery.isFetching}
                    />
                  </div>

                  <div className="cz-bulk-toggle">
                    <button
                      type="button"
                      className="cz-button cz-button--compact"
                      aria-pressed={bulkMode}
                      onClick={() => (bulkMode ? closeBulk() : setBulkMode(true))}
                    >
                      <CheckSquare size={15} aria-hidden="true" />
                      {bulkMode ? "Quitter la sélection" : "Sélection multiple"}
                    </button>
                  </div>

                  {bulkMode && (
                    <CasierBulkBar
                      ids={[...checked]}
                      totalVisible={casiers.length}
                      onSelectAll={checkAll}
                      onClear={() => setChecked(new Set())}
                      onClose={closeBulk}
                    />
                  )}

                  <div className="cz-panel-scroll">
                    <CasierList
                      casiers={casiers}
                      isLoading={listLoading}
                      isUpdating={casiersQuery.isPlaceholderData}
                      error={listError}
                      onRetry={() => casiersQuery.refetch()}
                      selectedId={effectiveCasierId}
                      onSelect={selectCasier}
                      searchQuery={searchQuery}
                      isFiltered={isFiltered}
                      resultsKey={resultsKey}
                      onClearFilters={resetFilters}
                      onCreate={openCreate}
                      selectable={bulkMode}
                      checkedIds={checked}
                      onToggleChecked={toggleChecked}
                    />
                  </div>
                </section>
              </div>

              <div className="cz-detail-col">
                {casierParam && (
                  <button type="button" className="cz-button cz-button--compact cz-back" onClick={backToList}>
                    <ArrowLeft size={16} aria-hidden="true" />
                    Retour à la liste
                  </button>
                )}

                {effectiveCasierId ? (
                  <CasierDetail
                    key={effectiveCasierId}
                    casierId={effectiveCasierId}
                    tab={detailTab}
                    onTabChange={changeDetailTab}
                    highlightSanctionId={sanctionParam}
                    highlightFlagId={vue === CASIER_VIEWS.casiers ? signalementParam : null}
                    onNavigate={navigate}
                    onBack={backToList}
                  />
                ) : listLoading ? (
                  <DetailSkeleton />
                ) : (
                  <div className="cz-detail-placeholder">
                    <MousePointerClick size={28} aria-hidden="true" />
                    <p>
                      {casiers.length > 0
                        ? "Sélectionnez un casier dans la liste."
                        : "Le détail d'un casier s'affichera ici."}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content
          value={CASIER_VIEWS.signalements}
          forceMount
          hidden={vue !== CASIER_VIEWS.signalements}
          className="cz-view"
        >
          {seen.signalements && (
            <AiFlagsView
              highlightFlagId={vue === CASIER_VIEWS.signalements ? signalementParam : null}
              onNavigate={navigate}
            />
          )}
        </Tabs.Content>
      </Tabs.Root>

      <CreateCasierModal open={createOpen} onClose={closeCreate} onCreated={handleCreated} />
    </section>
  );
}
