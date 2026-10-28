import { keepPreviousData } from "@tanstack/react-query";

import { api } from "../../api/client";
import {
  AGENDA_STALE_TIME,
  FILTERS_STORAGE_KEY,
  MEETING_DRAFT_STORAGE_PREFIX,
  MEETING_PHASE_ORDER,
  MEETINGS_PAGE_SIZE,
  TEXT_LIMITS,
  UPCOMING_DAYS,
  isValidAgendaId,
} from "./agendaConstants";
import { shouldRetryAgendaQuery } from "./agendaErrors";
import { sanitizeFilters } from "./calendarModel";
import { isIsoDate } from "./dateUtils";

export const LEGACY_UPLOAD_URL = "/staff/meetings/upload-image";

// ---- Clés React Query ----

export function normalizeMeetingParams(params) {
  const source = params && typeof params === "object" ? params : {};
  const q = typeof source.q === "string" ? source.q.trim().slice(0, TEXT_LIMITS.search) : "";
  const phase = MEETING_PHASE_ORDER.includes(source.phase) ? source.phase : "";
  const offset = Math.max(0, Math.floor(Number(source.offset) || 0));
  const limit = Math.min(200, Math.max(1, Math.floor(Number(source.limit) || MEETINGS_PAGE_SIZE)));
  return { q, phase, offset, limit };
}

export const agendaKeys = {
  all: ["agenda"],
  feedAll: ["agenda", "feed"],
  feed: (start, end) => ["agenda", "feed", start, end],
  upcoming: (days = UPCOMING_DAYS) => (days === UPCOMING_DAYS ? ["agenda", "upcoming"] : ["agenda", "upcoming", days]),
  meetingsAll: ["agenda", "meetings"],
  meetings: (params) => ["agenda", "meetings", normalizeMeetingParams(params)],
  // Liste paginée par « Afficher plus » (useInfiniteQuery) : clé distincte de `meetings`, même préfixe.
  meetingsPages: (params) => {
    const { q, phase } = normalizeMeetingParams(params);
    return ["agenda", "meetings", { q, phase, pages: true }];
  },
  meetingsOverview: ["agenda", "meetings", "overview"],
  meeting: (id) => ["agenda", "meeting", String(id)],
  absence: (id) => ["agenda", "absence", String(id)],
  entry: (id) => ["agenda", "entry", String(id)],
  people: ["agenda", "people"],
  settings: ["agenda", "settings"],
  dashboardAbsences: ["dashboard", "absences"],
};

// ---- Appels HTTP (un par endpoint du contrat ; chaque fonction renvoie `response.data`) ----

// Erreur au format axios, levée sans appel réseau quand l'identifiant ne peut pas être valide.
function notFoundError(message) {
  const error = new Error(message);
  error.response = { status: 404, data: { detail: message } };
  error.isClientCheck = true;
  return error;
}

function idSegment(id, notFoundMessage) {
  const value = id === null || id === undefined ? "" : String(id);
  if (!isValidAgendaId(value)) throw notFoundError(notFoundMessage);
  return encodeURIComponent(value);
}

const ABSENCE_NOT_FOUND = "Absence introuvable.";
const ENTRY_NOT_FOUND = "Entrée introuvable.";
const MEETING_NOT_FOUND = "Réunion introuvable.";
const ACTION_NOT_FOUND = "Action introuvable.";

export async function fetchFeed(start, end, { signal } = {}) {
  const response = await api.get("/agenda/feed", { params: { start, end }, signal });
  return response.data;
}

export async function fetchUpcoming(days = UPCOMING_DAYS, { signal } = {}) {
  const response = await api.get("/agenda/upcoming", { params: { days }, signal });
  return response.data;
}

export async function fetchAbsence(absenceId, { signal } = {}) {
  const response = await api.get(`/agenda/absences/${idSegment(absenceId, ABSENCE_NOT_FOUND)}`, { signal });
  return response.data;
}

export async function createAbsence(payload) {
  const response = await api.post("/agenda/absences", payload);
  return response.data;
}

export async function updateAbsence(absenceId, patch) {
  const response = await api.patch(`/agenda/absences/${idSegment(absenceId, ABSENCE_NOT_FOUND)}`, patch);
  return response.data;
}

// « Je suis de retour » : sans `returnDate`, le serveur prend la date du jour à Paris.
export async function returnFromAbsence(absenceId, returnDate) {
  const body = isIsoDate(returnDate) ? { return_date: returnDate } : {};
  const response = await api.post(`/agenda/absences/${idSegment(absenceId, ABSENCE_NOT_FOUND)}/return`, body);
  return response.data;
}

export async function deleteAbsence(absenceId) {
  await api.delete(`/agenda/absences/${idSegment(absenceId, ABSENCE_NOT_FOUND)}`);
  return null;
}

export async function createEntry(payload) {
  const response = await api.post("/agenda/entries", payload);
  return response.data;
}

export async function fetchEntry(entryId, { signal } = {}) {
  const response = await api.get(`/agenda/entries/${idSegment(entryId, ENTRY_NOT_FOUND)}`, { signal });
  return response.data;
}

export async function updateEntry(entryId, patch) {
  const response = await api.patch(`/agenda/entries/${idSegment(entryId, ENTRY_NOT_FOUND)}`, patch);
  return response.data;
}

export async function deleteEntry(entryId) {
  await api.delete(`/agenda/entries/${idSegment(entryId, ENTRY_NOT_FOUND)}`);
  return null;
}

// Glisser-déposer : décale une entrée ou une réunion de `deltaDays` jours (l'opposé annule).
export async function moveItem(kind, id, deltaDays) {
  const response = await api.post("/agenda/move", { kind, id: String(id), delta_days: deltaDays });
  return response.data;
}

export async function fetchMeetings(params = {}, { signal } = {}) {
  const { q, phase, offset, limit } = normalizeMeetingParams(params);
  const query = { limit, offset };
  if (q) query.q = q;
  if (phase) query.phase = phase;
  const response = await api.get("/agenda/meetings", { params: query, signal });
  return response.data;
}

export async function fetchMeetingsOverview({ signal } = {}) {
  const response = await api.get("/agenda/meetings/overview", { signal });
  return response.data;
}

export async function fetchMeeting(meetingId, { signal } = {}) {
  const response = await api.get(`/agenda/meetings/${idSegment(meetingId, MEETING_NOT_FOUND)}`, { signal });
  return response.data;
}

export async function createMeeting(payload) {
  const response = await api.post("/agenda/meetings", payload);
  return response.data;
}

// PATCH avec `expected_revision` obligatoire dans `patch`. `minimal` renvoie un MeetingSaveResult.
export async function updateMeeting(meetingId, patch, { minimal = false, signal } = {}) {
  const response = await api.patch(`/agenda/meetings/${idSegment(meetingId, MEETING_NOT_FOUND)}`, patch, {
    params: minimal ? { minimal: true } : undefined,
    signal,
  });
  return response.data;
}

// Enregistrement automatique (PATCH ?minimal=true).
export function saveMeetingMinimal(meetingId, patch, { signal } = {}) {
  return updateMeeting(meetingId, patch, { minimal: true, signal });
}

export async function toggleMeetingAction(meetingId, actionId, done) {
  const meetingSegment = idSegment(meetingId, MEETING_NOT_FOUND);
  const actionSegment = idSegment(actionId, ACTION_NOT_FOUND);
  const response = await api.patch(`/agenda/meetings/${meetingSegment}/actions/${actionSegment}`, { done: Boolean(done) });
  return response.data;
}

export async function setMeetingLock(meetingId, locked) {
  const response = await api.post(`/agenda/meetings/${idSegment(meetingId, MEETING_NOT_FOUND)}/lock`, {
    locked: Boolean(locked),
  });
  return response.data;
}

export async function deleteMeeting(meetingId) {
  await api.delete(`/agenda/meetings/${idSegment(meetingId, MEETING_NOT_FOUND)}`);
  return null;
}

export async function fetchPeople({ signal } = {}) {
  const response = await api.get("/agenda/people", { signal });
  return Array.isArray(response.data) ? response.data : [];
}

export async function fetchSettings({ signal } = {}) {
  const response = await api.get("/agenda/settings", { signal });
  return response.data;
}

export async function updateSettings(payload) {
  const response = await api.put("/agenda/settings", payload);
  return response.data;
}

export async function sendSettingsTest({ ping = false } = {}) {
  const response = await api.post("/agenda/settings/test", { ping: Boolean(ping) });
  return response.data;
}

// Ancien endpoint d'envoi d'image (toujours utilisé par l'éditeur) : renvoie { url } relative.
export async function uploadMeetingImage(file, uploadUrl = LEGACY_UPLOAD_URL) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post(uploadUrl, formData);
  return response.data;
}

// ---- Options de requêtes (à étaler dans useQuery) ----

// Décalage de la page suivante de GET /agenda/meetings, ou undefined quand tout est chargé.
export function nextMeetingsOffset(lastPage) {
  const items = Array.isArray(lastPage?.items) ? lastPage.items : [];
  const offset = Number(lastPage?.offset) || 0;
  const total = Number(lastPage?.total) || 0;
  const next = offset + items.length;
  return items.length > 0 && next < total ? next : undefined;
}

// Pages chargées (données de useInfiniteQuery) → { items, total, counts, viewer } ; une réunion décalée d'une
// page à l'autre par une création entre deux chargements n'apparaît qu'une fois.
export function flattenMeetingPages(data) {
  const pages = Array.isArray(data?.pages) ? data.pages.filter(Boolean) : [];
  const seen = new Set();
  const items = [];
  for (const page of pages) {
    for (const item of Array.isArray(page.items) ? page.items : []) {
      if (!item?.id || seen.has(item.id)) continue;
      seen.add(item.id);
      items.push(item);
    }
  }
  const last = pages[pages.length - 1] || null;
  return {
    items,
    total: Number(last?.total) || 0,
    counts: last?.counts || null,
    viewer: last?.viewer || null,
  };
}

const listDefaults = {
  staleTime: AGENDA_STALE_TIME,
  refetchOnWindowFocus: true,
  retry: shouldRetryAgendaQuery,
};

// Montage de la page réunion : une copie en cache de plus de 30 s (laissée par le tiroir du calendrier) ou
// invalidée est relue ; une copie récente (enregistrement automatique, MeetingDialog) est gardée telle quelle.
function refetchEditorOnMount(query) {
  const updatedAt = Number(query?.state?.dataUpdatedAt) || 0;
  return Date.now() - updatedAt > AGENDA_STALE_TIME ? "always" : true;
}

export const agendaQueries = {
  feed: (start, end) => ({
    ...listDefaults,
    queryKey: agendaKeys.feed(start, end),
    queryFn: ({ signal }) => fetchFeed(start, end, { signal }),
    enabled: isIsoDate(start) && isIsoDate(end),
    placeholderData: keepPreviousData,
  }),
  upcoming: (days = UPCOMING_DAYS) => ({
    ...listDefaults,
    queryKey: agendaKeys.upcoming(days),
    queryFn: ({ signal }) => fetchUpcoming(days, { signal }),
  }),
  meetings: (params) => ({
    ...listDefaults,
    queryKey: agendaKeys.meetings(params),
    queryFn: ({ signal }) => fetchMeetings(params, { signal }),
    placeholderData: keepPreviousData,
  }),
  // Pour useInfiniteQuery : pages de MEETINGS_PAGE_SIZE réunions, « Afficher plus » = fetchNextPage().
  meetingsPages: (params) => {
    const { q, phase } = normalizeMeetingParams(params);
    return {
      ...listDefaults,
      queryKey: agendaKeys.meetingsPages({ q, phase }),
      queryFn: ({ pageParam, signal }) =>
        fetchMeetings({ q, phase, offset: pageParam, limit: MEETINGS_PAGE_SIZE }, { signal }),
      initialPageParam: 0,
      getNextPageParam: nextMeetingsOffset,
      placeholderData: keepPreviousData,
    };
  },
  meetingsOverview: () => ({
    ...listDefaults,
    queryKey: agendaKeys.meetingsOverview,
    queryFn: ({ signal }) => fetchMeetingsOverview({ signal }),
  }),
  meeting: (meetingId) => ({
    ...listDefaults,
    queryKey: agendaKeys.meeting(meetingId),
    queryFn: ({ signal }) => fetchMeeting(meetingId, { signal }),
    enabled: isValidAgendaId(String(meetingId ?? "")),
  }),
  // Page réunion : lu une seule fois, l'état local de l'éditeur fait foi ensuite (même clé que `meeting`).
  meetingEditor: (meetingId) => ({
    queryKey: agendaKeys.meeting(meetingId),
    queryFn: ({ signal }) => fetchMeeting(meetingId, { signal }),
    enabled: isValidAgendaId(String(meetingId ?? "")),
    staleTime: Infinity,
    refetchOnMount: refetchEditorOnMount,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: shouldRetryAgendaQuery,
  }),
  absence: (absenceId) => ({
    ...listDefaults,
    queryKey: agendaKeys.absence(absenceId),
    queryFn: ({ signal }) => fetchAbsence(absenceId, { signal }),
    enabled: isValidAgendaId(String(absenceId ?? "")),
  }),
  entry: (entryId) => ({
    ...listDefaults,
    queryKey: agendaKeys.entry(entryId),
    queryFn: ({ signal }) => fetchEntry(entryId, { signal }),
    enabled: isValidAgendaId(String(entryId ?? "")),
  }),
  people: () => ({
    queryKey: agendaKeys.people,
    queryFn: ({ signal }) => fetchPeople({ signal }),
    staleTime: 300_000,
    refetchOnWindowFocus: false,
    retry: shouldRetryAgendaQuery,
  }),
  settings: () => ({
    ...listDefaults,
    queryKey: agendaKeys.settings,
    queryFn: ({ signal }) => fetchSettings({ signal }),
  }),
};

// Requête de détail d'un élément désigné par `?element=` ({ kind, id } de parseElementParam).
export function elementQuery(element) {
  if (element?.kind === "absence") return agendaQueries.absence(element.id);
  if (element?.kind === "meeting") return agendaQueries.meeting(element.id);
  if (element?.kind === "entry") return agendaQueries.entry(element.id);
  return { queryKey: ["agenda", "element", "aucun"], queryFn: () => null, enabled: false };
}

// ---- Invalidation et mise à jour du cache ----

// Mutation hors enregistrement automatique : invalide tout ["agenda"] sauf le détail de la réunion
// ouverte dans l'éditeur (`exceptMeetingId`, mise à jour par setQueryData). `includeDashboard` invalide
// aussi ["dashboard","absences"] (pastille de présence du tableau de bord).
export function invalidateAgenda(queryClient, { exceptMeetingId = null, includeDashboard = false } = {}) {
  const except = exceptMeetingId === null || exceptMeetingId === undefined ? null : String(exceptMeetingId);
  const tasks = [
    queryClient.invalidateQueries({
      queryKey: agendaKeys.all,
      predicate: (query) => !(except && query.queryKey[1] === "meeting" && query.queryKey[2] === except),
    }),
  ];
  if (includeDashboard) tasks.push(queryClient.invalidateQueries({ queryKey: agendaKeys.dashboardAbsences }));
  return Promise.all(tasks);
}

// Après toute mutation d'absence (création, modification, retour, suppression).
export function invalidateAfterAbsenceChange(queryClient) {
  return invalidateAgenda(queryClient, { includeDashboard: true });
}

// Listes seulement (éditeur inactif depuis 5 s, ou démontage) : réunions, vue d'ensemble, flux, à venir.
// `meetingId` (au démontage de l'éditeur) marque aussi le détail comme périmé, sans le recharger : le tiroir
// du calendrier le relira au lieu d'afficher la présence ou l'ordre du jour d'avant l'enregistrement automatique.
export function invalidateAgendaLists(queryClient, { meetingId = null } = {}) {
  const tasks = [
    queryClient.invalidateQueries({ queryKey: agendaKeys.meetingsAll }),
    queryClient.invalidateQueries({ queryKey: agendaKeys.feedAll }),
    queryClient.invalidateQueries({ queryKey: ["agenda", "upcoming"] }),
  ];
  if (meetingId !== null && meetingId !== undefined && meetingId !== "") {
    tasks.push(
      queryClient.invalidateQueries({ queryKey: agendaKeys.meeting(meetingId), exact: true, refetchType: "none" }),
    );
  }
  return Promise.all(tasks);
}

export function setMeetingDetail(queryClient, detail) {
  if (!detail?.id) return;
  queryClient.setQueryData(agendaKeys.meeting(detail.id), detail);
}

// Réponse complète d'une mutation de réunion (MeetingDialog, verrouillage, annulation) : met à jour le
// détail puis invalide le reste de l'agenda.
export function commitMeetingDetail(queryClient, detail) {
  setMeetingDetail(queryClient, detail);
  return invalidateAgenda(queryClient, { exceptMeetingId: detail?.id ?? null });
}

// Enregistrement automatique : n'invalide rien, recopie seulement les champs du MeetingSaveResult.
export function applyMeetingSaveResult(queryClient, meetingId, result) {
  if (!result) return;
  queryClient.setQueryData(agendaKeys.meeting(meetingId), (old) =>
    old
      ? {
          ...old,
          revision: result.revision,
          updated_at: result.updated_at,
          updated_by: result.updated_by,
          status: result.status,
          phase: result.phase,
          word_count: result.word_count,
        }
      : old,
  );
}

// Réponse de PATCH …/actions/{id} ({ meeting_id, revision, item }) : met à jour le détail et la vue d'ensemble.
export function applyActionToggleResult(queryClient, result) {
  const item = result?.item;
  const meetingId = result?.meeting_id;
  if (!item || !meetingId) return;
  queryClient.setQueryData(agendaKeys.meeting(meetingId), (old) =>
    old && Array.isArray(old.action_items)
      ? { ...old, action_items: old.action_items.map((action) => (action.id === item.id ? item : action)) }
      : old,
  );
  queryClient.setQueryData(agendaKeys.meetingsOverview, (old) =>
    old && Array.isArray(old.open_actions)
      ? {
          ...old,
          open_actions: old.open_actions.map((entry) =>
            entry.meeting_id === meetingId && entry.item?.id === item.id ? { ...entry, item } : entry,
          ),
        }
      : old,
  );
}

// ---- Corps des PATCH ----

function sameValue(a, b) {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

// Champs de `keys` dont la valeur diffère entre `initial` et `current` (null explicite conservé).
export function buildPatch(initial, current, keys) {
  const patch = {};
  for (const key of keys) {
    const before = initial?.[key] === undefined ? null : initial[key];
    const after = current?.[key] === undefined ? null : current[key];
    if (!sameValue(before, after)) patch[key] = after;
  }
  return patch;
}

export function isEmptyPatch(patch) {
  return !patch || Object.keys(patch).length === 0;
}

// ---- Préférences locales (try/catch : la page marche sans stockage) ----

export function readStoredFilters() {
  try {
    const raw = window.localStorage.getItem(FILTERS_STORAGE_KEY);
    return sanitizeFilters(raw ? JSON.parse(raw) : null);
  } catch (error) {
    return sanitizeFilters(null);
  }
}

export function writeStoredFilters(filters) {
  try {
    window.localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(sanitizeFilters(filters)));
  } catch (error) {
    // Stockage indisponible (navigation privée, quota) : les filtres restent en mémoire.
  }
}

// Brouillon local d'une réunion : { revision, content, saved_at }.
export function readMeetingDraft(meetingId) {
  try {
    const raw = window.localStorage.getItem(`${MEETING_DRAFT_STORAGE_PREFIX}${meetingId}`);
    const draft = raw ? JSON.parse(raw) : null;
    return draft && typeof draft === "object" && typeof draft.content === "string" ? draft : null;
  } catch (error) {
    return null;
  }
}

export function writeMeetingDraft(meetingId, { revision, content } = {}) {
  try {
    window.localStorage.setItem(
      `${MEETING_DRAFT_STORAGE_PREFIX}${meetingId}`,
      JSON.stringify({ revision, content, saved_at: new Date().toISOString() }),
    );
    return true;
  } catch (error) {
    return false;
  }
}

export function clearMeetingDraft(meetingId) {
  try {
    window.localStorage.removeItem(`${MEETING_DRAFT_STORAGE_PREFIX}${meetingId}`);
  } catch (error) {
    // Stockage indisponible : rien à effacer.
  }
}
