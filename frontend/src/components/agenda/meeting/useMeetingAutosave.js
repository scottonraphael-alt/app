import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  applyMeetingSaveResult,
  clearMeetingDraft,
  fetchMeeting,
  invalidateAgendaLists,
  saveMeetingMinimal,
  setMeetingDetail,
} from "../agendaApi";
import {
  agendaErrorMessage,
  errorStatus,
  isCancelledRequest,
  isLockedError,
  isRetryableError,
  isRevisionConflict,
  isValidationError,
  revisionConflictInfo,
} from "../agendaErrors";
import { buildSavePatch } from "./meetingModel";

const CONTENT_DELAY_MS = 1200;
const LIST_DELAY_MS = 600;
// Une frappe continue finit quand même par partir.
const MAX_WAIT_MS = 8000;
const RETRY_DELAYS_S = [2, 5, 10, 30];
const IDLE_INVALIDATE_MS = 5000;

function delayFor(key) {
  return key === "content_markdown" ? CONTENT_DELAY_MS : LIST_DELAY_MS;
}

// Enregistrement automatique de la page réunion : un patch en attente qui fusionne les champs modifiés,
// un seul envoi à la fois, essais espacés en cas d'erreur passagère, arrêt sur conflit ou verrouillage.
// `getDoc()` renvoie l'état local courant (source de vérité) ; `onLocked()` est appelé sur un 403 « verrouillé ».
export default function useMeetingAutosave({ meetingId, initialRevision, getDoc, onLocked }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState({ status: "idle", message: "", retryAt: 0, savedAt: 0, conflict: null });
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  const [now, setNow] = useState(() => Date.now());

  const revisionRef = useRef(Number(initialRevision) || 0);
  const dirtyRef = useRef(new Set());
  const doneRef = useRef(new Map());
  const attendanceRef = useRef(new Map());
  const debounceRef = useRef(null);
  const retryRef = useRef(null);
  const idleRef = useRef(null);
  const sendingRef = useRef(null);
  const blockedRef = useRef(null); // "conflict" | "locked" | "discarded" | null
  const failuresRef = useRef(0);
  const firstDirtyAtRef = useRef(0);
  const savedSinceInvalidateRef = useRef(false);
  const mountedRef = useRef(true);
  const getDocRef = useRef(getDoc);
  const onLockedRef = useRef(onLocked);
  const statusRef = useRef("idle");

  getDocRef.current = getDoc;
  onLockedRef.current = onLocked;

  const publish = useCallback((patch) => {
    if (patch.status) statusRef.current = patch.status;
    if (mountedRef.current) setState((old) => ({ ...old, ...patch }));
  }, []);

  const hasDirty = () => dirtyRef.current.size > 0 || doneRef.current.size > 0 || attendanceRef.current.size > 0;

  const clearTimer = (ref) => {
    if (ref.current) {
      window.clearTimeout(ref.current);
      ref.current = null;
    }
  };

  const scheduleIdleInvalidate = useCallback(() => {
    clearTimer(idleRef);
    if (!savedSinceInvalidateRef.current) return;
    idleRef.current = window.setTimeout(() => {
      idleRef.current = null;
      if (hasDirty() || sendingRef.current) return;
      savedSinceInvalidateRef.current = false;
      invalidateAgendaLists(queryClient);
    }, IDLE_INVALIDATE_MS);
  }, [queryClient]);

  const runSend = useCallback(async () => {
    while (hasDirty() && !blockedRef.current) {
      const keys = new Set(dirtyRef.current);
      const done = new Map(doneRef.current);
      const attendance = new Map(attendanceRef.current);
      dirtyRef.current = new Set();
      const doc = getDocRef.current();
      const patch = buildSavePatch(doc, keys, { done, attendance });
      if (!Object.keys(patch).length) {
        doneRef.current = new Map();
        attendanceRef.current = new Map();
        continue;
      }
      publish({ status: "saving", message: "", retryAt: 0 });
      try {
        const result = await saveMeetingMinimal(meetingId, { expected_revision: revisionRef.current, ...patch });
        revisionRef.current = Number.isInteger(result?.revision) ? result.revision : revisionRef.current + 1;
        applyMeetingSaveResult(queryClient, meetingId, result);
        // Une action recochée pendant l'envoi garde sa marque pour l'envoi suivant.
        for (const [id, value] of done) if (doneRef.current.get(id) === value) doneRef.current.delete(id);
        for (const [id, value] of attendance) if (attendanceRef.current.get(id) === value) attendanceRef.current.delete(id);
        failuresRef.current = 0;
        savedSinceInvalidateRef.current = true;
        if (patch.content_markdown !== undefined && getDocRef.current().content === patch.content_markdown) {
          clearMeetingDraft(meetingId);
        }
        publish({ status: hasDirty() ? "pending" : "saved", savedAt: Date.now(), message: "", conflict: null });
      } catch (error) {
        // Ce qui n'est pas parti revient dans la file.
        for (const key of keys) dirtyRef.current.add(key);
        if (isCancelledRequest(error)) {
          publish({ status: "pending" });
          return false;
        }
        if (isRevisionConflict(error)) {
          blockedRef.current = "conflict";
          publish({ status: "conflict", conflict: revisionConflictInfo(error), message: "" });
          return false;
        }
        if (isLockedError(error)) {
          blockedRef.current = "locked";
          publish({ status: "locked", message: "" });
          if (mountedRef.current) onLockedRef.current?.();
          return false;
        }
        if (isRetryableError(error)) {
          const delay = RETRY_DELAYS_S[Math.min(failuresRef.current, RETRY_DELAYS_S.length - 1)];
          failuresRef.current += 1;
          const retryAt = Date.now() + delay * 1000;
          publish({ status: "error", message: agendaErrorMessage(error), retryAt });
          clearTimer(retryRef);
          if (mountedRef.current) {
            retryRef.current = window.setTimeout(() => {
              retryRef.current = null;
              void runSendOnce();
            }, delay * 1000);
          }
          return false;
        }
        // 422, 404, autre 4xx : pas de nouvel essai automatique.
        const fallback = errorStatus(error) === 404 ? "Réunion introuvable." : undefined;
        publish({
          status: "error",
          message: isValidationError(error) ? agendaErrorMessage(error) : agendaErrorMessage(error, fallback),
          retryAt: 0,
        });
        return false;
      }
    }
    return !blockedRef.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId, queryClient, publish]);

  const runSendOnce = useCallback(async () => {
    if (sendingRef.current) return sendingRef.current;
    const promise = runSend().finally(() => {
      sendingRef.current = null;
      if (mountedRef.current) scheduleIdleInvalidate();
    });
    sendingRef.current = promise;
    return promise;
  }, [runSend, scheduleIdleInvalidate]);

  const schedule = useCallback(
    (delay) => {
      clearTimer(debounceRef);
      clearTimer(idleRef);
      if (blockedRef.current) return;
      const elapsed = Date.now() - firstDirtyAtRef.current;
      const wait = Math.max(0, Math.min(delay, MAX_WAIT_MS - elapsed));
      debounceRef.current = window.setTimeout(() => {
        debounceRef.current = null;
        void runSendOnce();
      }, wait);
    },
    [runSendOnce],
  );

  const markDirty = useCallback(() => {
    if (!firstDirtyAtRef.current) firstDirtyAtRef.current = Date.now();
    clearTimer(retryRef);
    if (!blockedRef.current && statusRef.current !== "saving") publish({ status: "pending", message: "", retryAt: 0 });
  }, [publish]);

  // Champ(s) modifié(s) : "title", "content_markdown", "agenda_items", "decisions", "action_items".
  const touch = useCallback(
    (key) => {
      dirtyRef.current.add(key);
      markDirty();
      schedule(delayFor(key));
    },
    [markDirty, schedule],
  );

  const touchDone = useCallback(
    (actionId, done) => {
      doneRef.current.set(actionId, Boolean(done));
      dirtyRef.current.add("action_items");
      markDirty();
      schedule(LIST_DELAY_MS);
    },
    [markDirty, schedule],
  );

  const touchAttendance = useCallback(
    (personId, value) => {
      attendanceRef.current.set(String(personId), value);
      markDirty();
      schedule(LIST_DELAY_MS);
    },
    [markDirty, schedule],
  );

  // Envoie tout de suite ce qui est en attente. Renvoie { ok, revision } : ok = rien ne reste à envoyer.
  const flush = useCallback(async () => {
    clearTimer(debounceRef);
    clearTimer(retryRef);
    if (hasDirty() && !blockedRef.current) {
      await runSendOnce();
      if (hasDirty() && !blockedRef.current && !sendingRef.current) await runSendOnce();
    } else if (sendingRef.current) {
      await sendingRef.current;
    }
    return { ok: !hasDirty() && !blockedRef.current, revision: revisionRef.current };
  }, [runSendOnce]);

  const retryNow = useCallback(() => {
    clearTimer(retryRef);
    clearTimer(debounceRef);
    return runSendOnce();
  }, [runSendOnce]);

  const setRevision = useCallback((revision) => {
    if (Number.isInteger(revision)) revisionRef.current = revision;
  }, []);

  const getRevision = useCallback(() => revisionRef.current, []);

  // « Garder ma version » : on repart de la révision du serveur et on renvoie ce qui était en attente.
  const keepMine = useCallback(async () => {
    const info = state.conflict;
    let revision = info?.currentRevision;
    if (!Number.isInteger(revision)) {
      const detail = await fetchMeeting(meetingId);
      revision = detail.revision;
    }
    revisionRef.current = revision;
    blockedRef.current = null;
    publish({ status: "pending", conflict: null, message: "" });
    return runSendOnce();
  }, [meetingId, publish, runSendOnce, state.conflict]);

  // « Recharger leur version » : lit la version du serveur et abandonne les modifications en attente
  // (le brouillon local du contenu reste dans le navigateur). L'appelant remplace l'état local.
  const reloadTheirs = useCallback(async () => {
    const detail = await fetchMeeting(meetingId);
    clearTimer(debounceRef);
    clearTimer(retryRef);
    dirtyRef.current = new Set();
    doneRef.current = new Map();
    attendanceRef.current = new Map();
    firstDirtyAtRef.current = 0;
    failuresRef.current = 0;
    revisionRef.current = Number(detail.revision) || 0;
    blockedRef.current = null;
    setMeetingDetail(queryClient, detail);
    publish({ status: "saved", conflict: null, message: "", retryAt: 0, savedAt: Date.now() });
    return detail;
  }, [meetingId, publish, queryClient]);

  // Réunion supprimée : plus rien à envoyer.
  const discard = useCallback(() => {
    clearTimer(debounceRef);
    clearTimer(retryRef);
    clearTimer(idleRef);
    dirtyRef.current = new Set();
    doneRef.current = new Map();
    attendanceRef.current = new Map();
    blockedRef.current = "discarded";
    savedSinceInvalidateRef.current = false;
  }, []);

  const hasUnsaved = useCallback(() => hasDirty() || Boolean(sendingRef.current), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer(debounceRef);
      clearTimer(retryRef);
      clearTimer(idleRef);
      // Départ de la page : on envoie ce qui reste, puis on marque le détail comme périmé pour les autres vues.
      let last = sendingRef.current || Promise.resolve();
      if (hasDirty() && !blockedRef.current) last = last.then(() => runSendOnce());
      last
        .catch(() => undefined)
        .then(() => {
          if (savedSinceInvalidateRef.current) {
            savedSinceInvalidateRef.current = false;
            invalidateAgendaLists(queryClient, { meetingId });
          }
        });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onBeforeUnload = (event) => {
      if (blockedRef.current === "discarded") return;
      if (hasDirty() || sendingRef.current || statusRef.current === "error") {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      if (statusRef.current === "error" && hasDirty() && !blockedRef.current) void retryNow();
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, [retryNow]);

  // Décompte « nouvel essai dans 10 s ».
  useEffect(() => {
    if (state.status !== "error" || !state.retryAt) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.status, state.retryAt]);

  const retryIn = state.status === "error" && state.retryAt ? Math.max(1, Math.ceil((state.retryAt - now) / 1000)) : 0;

  return {
    status: state.status,
    message: state.message,
    savedAt: state.savedAt,
    conflict: state.conflict,
    online,
    retryIn,
    touch,
    touchDone,
    touchAttendance,
    flush,
    retryNow,
    keepMine,
    reloadTheirs,
    setRevision,
    getRevision,
    discard,
    hasUnsaved,
  };
}
