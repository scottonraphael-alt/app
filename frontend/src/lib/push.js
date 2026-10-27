// Notifications push (Web Push) : service worker, abonnement et appels API.
import { api } from "../api/client";

const SW_URL = "/sw.js";

export function isStandalone() {
  try {
    return (
      (typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  } catch (error) {
    return false;
  }
}

function isIos() {
  const ua = window.navigator.userAgent || "";
  return (
    /iPad|iPhone|iPod/.test(ua) ||
    (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1)
  );
}

/** { supported: boolean, reason: "" | "ios-install" | "insecure" | "unsupported" } */
export function getPushSupport() {
  if (typeof window === "undefined") return { supported: false, reason: "unsupported" };
  if (isIos() && !isStandalone()) return { supported: false, reason: "ios-install" };
  if (!window.isSecureContext) return { supported: false, reason: "insecure" };
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return { supported: false, reason: "unsupported" };
  }
  return { supported: true, reason: "" };
}

export function unsupportedMessage(reason) {
  if (reason === "ios-install") {
    return "Sur iPhone et iPad, les notifications ne fonctionnent que si Iris est ajouté à l’écran d’accueil (Partager, puis « Sur l’écran d’accueil »). Ouvrez ensuite Iris depuis cette icône.";
  }
  if (reason === "insecure") {
    return "Les notifications nécessitent une connexion sécurisée (https).";
  }
  return "Ce navigateur ne permet pas les notifications sur l’appareil.";
}

export async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    return await navigator.serviceWorker.register(SW_URL);
  } catch (error) {
    return null;
  }
}

/** Enregistre le service worker en production, ou si une notification est déjà activée. Ne lève jamais. */
export async function registerServiceWorkerIfNeeded() {
  try {
    if (!("serviceWorker" in navigator)) return null;
    if (process.env.NODE_ENV === "production") return await registerServiceWorker();
    const existing = await navigator.serviceWorker.getRegistration(SW_URL);
    return existing || null;
  } catch (error) {
    return null;
  }
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

/** GET /api/push/config -> { enabled: bool, public_key: string } */
export async function fetchPushConfig() {
  const response = await api.get("/push/config");
  return response.data;
}

async function readyRegistration() {
  const registration = await registerServiceWorker();
  if (!registration) throw new Error("Le service worker n’a pas pu être enregistré.");
  return navigator.serviceWorker.ready;
}

/** Abonnement actuel de cet appareil, ou null. */
export async function getCurrentSubscription() {
  try {
    if (!getPushSupport().supported) return null;
    const registration = await navigator.serviceWorker.getRegistration(SW_URL);
    if (!registration) return null;
    return await registration.pushManager.getSubscription();
  } catch (error) {
    return null;
  }
}

/**
 * Active les notifications sur cet appareil.
 * Retourne { ok: true } ou { ok: false, reason: "denied" | "dismissed" | "disabled" | "error" }.
 */
export async function enablePush(config) {
  if (!config?.enabled || !config.public_key) return { ok: false, reason: "disabled" };
  const permission = await Notification.requestPermission();
  if (permission === "denied") return { ok: false, reason: "denied" };
  if (permission !== "granted") return { ok: false, reason: "dismissed" };

  const registration = await readyRegistration();
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key),
    });
  }
  const json = subscription.toJSON();
  await api.post("/push/subscribe", { endpoint: json.endpoint, keys: json.keys });
  return { ok: true };
}

export async function disablePush() {
  const subscription = await getCurrentSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  try {
    await api.delete("/push/subscribe", { data: { endpoint } });
  } finally {
    await subscription.unsubscribe();
  }
}

/** POST /api/push/test -> { enabled, sent, failed, removed } */
export async function sendPushTest() {
  const response = await api.post("/push/test");
  return response.data;
}
