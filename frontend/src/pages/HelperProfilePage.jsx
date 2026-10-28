import { useEffect, useState } from "react";
import {
  ArrowRight,
  BellRing,
  CalendarDays,
  Copy,
  LoaderCircle,
  Save,
  ShieldCheck,
  Smartphone,
  UserRound,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import {
  disablePush,
  enablePush,
  fetchPushConfig,
  getCurrentSubscription,
  getPushSupport,
  registerServiceWorkerIfNeeded,
  sendPushTest,
  unsupportedMessage,
} from "../lib/push";
import DisplayPrefsSection from "../components/ux/DisplayPrefsSection";
import "../Profile.css";

const PREF_LABELS = [
  ["ticket_assigned", "Suivi attribué"],
  ["task_assigned", "Tâche attribuée"],
  ["meeting_action", "Action de réunion attribuée"],
  ["due_soon", "Échéance proche ou dépassée"],
  ["mention", "Mention"],
];

const DEFAULT_PREFS = {
  types: Object.fromEntries(PREF_LABELS.map(([key]) => [key, true])),
  quiet_hours: { enabled: false, start: "22:00", end: "08:00" },
};

function NotificationPrefsSection() {
  const [prefs, setPrefs] = useState(null);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    api
      .get("/notifications/preferences")
      .then((response) => {
        if (!active) return;
        const data = {
          types: { ...DEFAULT_PREFS.types, ...(response.data?.types || {}) },
          quiet_hours: { ...DEFAULT_PREFS.quiet_hours, ...(response.data?.quiet_hours || {}) },
        };
        setPrefs(data);
        setSaved(JSON.stringify(data));
      })
      .catch((err) => {
        if (active) setError(getErrorMessage(err));
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const dirty = prefs ? JSON.stringify(prefs) !== saved : false;

  const setType = (key, value) =>
    setPrefs((current) => ({ ...current, types: { ...current.types, [key]: value } }));
  const setQuiet = (key, value) =>
    setPrefs((current) => ({ ...current, quiet_hours: { ...current.quiet_hours, [key]: value } }));

  const save = async (event) => {
    event.preventDefault();
    if (!prefs || saving || !dirty) return;
    setSaving(true);
    try {
      const response = await api.put("/notifications/preferences", {
        types: prefs.types,
        quiet_hours: prefs.quiet_hours,
      });
      const data = {
        types: { ...DEFAULT_PREFS.types, ...(response.data?.types || prefs.types) },
        quiet_hours: { ...DEFAULT_PREFS.quiet_hours, ...(response.data?.quiet_hours || prefs.quiet_hours) },
      };
      setPrefs(data);
      setSaved(JSON.stringify(data));
      toast.success("Préférences de notifications enregistrées.");
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="hp-extra-card" aria-labelledby="hp-notif-title" data-testid="helper-notifications-prefs">
      <header className="hp-extra-header">
        <span className="hp-card-icon">
          <BellRing size={22} aria-hidden="true" />
        </span>
        <div>
          <p className="hp-eyebrow">NOTIFICATIONS</p>
          <h2 id="hp-notif-title">Ce que je souhaite recevoir</h2>
        </div>
      </header>

      <div className="hp-extra-body">
        {error ? (
          <div className="hp-load-error" role="alert">
            <h3>Les préférences n’ont pas pu être chargées.</h3>
            <p>{error}</p>
            <button type="button" className="hp-secondary-button" onClick={() => setReloadKey((v) => v + 1)}>
              Réessayer
            </button>
          </div>
        ) : !prefs ? (
          <div className="hp-state" role="status">
            <LoaderCircle className="hp-spin" size={20} aria-hidden="true" />
            Chargement des préférences…
          </div>
        ) : (
          <form onSubmit={save} className="hp-extra-form">
            <fieldset className="hp-fieldset">
              <legend>Types de notifications</legend>
              {PREF_LABELS.map(([key, label]) => (
                <label key={key} className="hp-switch-row">
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    className="hp-switch"
                    checked={Boolean(prefs.types[key])}
                    onChange={(event) => setType(key, event.target.checked)}
                    disabled={saving}
                  />
                </label>
              ))}
            </fieldset>

            <fieldset className="hp-fieldset">
              <legend>Heures calmes</legend>
              <label className="hp-switch-row">
                <span>Ne pas me déranger pendant ces heures</span>
                <input
                  type="checkbox"
                  role="switch"
                  className="hp-switch"
                  checked={Boolean(prefs.quiet_hours.enabled)}
                  onChange={(event) => setQuiet("enabled", event.target.checked)}
                  disabled={saving}
                />
              </label>
              <div className="hp-time-row">
                <label htmlFor="hp-quiet-start">
                  De
                  <input
                    id="hp-quiet-start"
                    type="time"
                    value={prefs.quiet_hours.start}
                    onChange={(event) => setQuiet("start", event.target.value)}
                    disabled={saving || !prefs.quiet_hours.enabled}
                    required
                  />
                </label>
                <label htmlFor="hp-quiet-end">
                  À
                  <input
                    id="hp-quiet-end"
                    type="time"
                    value={prefs.quiet_hours.end}
                    onChange={(event) => setQuiet("end", event.target.value)}
                    disabled={saving || !prefs.quiet_hours.enabled}
                    required
                  />
                </label>
              </div>
              <p className="hp-extra-note">
                Heure de Paris. Pendant les heures calmes, les notifications arrivent dans Iris
                sans alerte sur votre appareil.
              </p>
            </fieldset>

            <footer className="hp-save-footer">
              <span className={`hp-save-state ${dirty ? "has-changes" : ""}`} role="status">
                {saving
                  ? "Enregistrement en cours…"
                  : dirty
                    ? "Modifications non enregistrées"
                    : "Aucune modification en attente"}
              </span>
              <button className="hp-save-button" type="submit" disabled={saving || !dirty}>
                {saving ? (
                  <LoaderCircle className="hp-spin" size={17} aria-hidden="true" />
                ) : (
                  <Save size={17} aria-hidden="true" />
                )}
                {saving ? "Enregistrement…" : "Enregistrer les préférences"}
              </button>
            </footer>
          </form>
        )}
      </div>
    </section>
  );
}

function DevicePushSection() {
  const [support] = useState(() => getPushSupport());
  const [config, setConfig] = useState(null);
  const [configError, setConfigError] = useState("");
  const [subscribed, setSubscribed] = useState(false);
  const [permission, setPermission] = useState(() =>
    typeof Notification !== "undefined" ? Notification.permission : "default",
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    fetchPushConfig()
      .then((data) => {
        if (active) setConfig(data);
      })
      .catch((err) => {
        if (active) setConfigError(getErrorMessage(err));
      });

    if (support.supported) {
      registerServiceWorkerIfNeeded().then(() => getCurrentSubscription()).then((sub) => {
        if (active) setSubscribed(Boolean(sub));
      });
    }
    return () => {
      active = false;
    };
  }, [support.supported]);

  const activate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await enablePush(config);
      setPermission(typeof Notification !== "undefined" ? Notification.permission : "default");
      if (result.ok) {
        setSubscribed(true);
        toast.success("Notifications activées sur cet appareil.");
      } else if (result.reason === "denied") {
        toast.error("Les notifications sont bloquées pour ce site. Autorisez-les dans les réglages du navigateur.");
      } else if (result.reason === "dismissed") {
        toast.message("Autorisation non accordée.");
      } else {
        toast.error("Les notifications ne sont pas disponibles sur le serveur.");
      }
    } catch (err) {
      toast.error(err?.response ? getErrorMessage(err) : "L’activation des notifications a échoué.");
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await disablePush();
      setSubscribed(false);
      toast.success("Notifications désactivées sur cet appareil.");
    } catch (err) {
      toast.error(err?.response ? getErrorMessage(err) : "La désactivation a échoué.");
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await sendPushTest();
      if (!result.enabled) toast.error("Les notifications push ne sont pas configurées sur le serveur.");
      else if (result.sent > 0) toast.success("Notification de test envoyée.");
      else toast.error("Aucun appareil n’a pu recevoir le test. Réactivez les notifications sur cet appareil.");
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  let body;
  if (!support.supported) {
    body = <p className="hp-extra-note hp-notice">{unsupportedMessage(support.reason)}</p>;
  } else if (configError) {
    body = <p className="hp-extra-note hp-notice" role="alert">{configError}</p>;
  } else if (!config) {
    body = (
      <div className="hp-state" role="status">
        <LoaderCircle className="hp-spin" size={20} aria-hidden="true" />
        Vérification…
      </div>
    );
  } else if (!config.enabled) {
    body = (
      <p className="hp-extra-note hp-notice">
        Les notifications sur appareil ne sont pas encore activées côté serveur. Les notifications restent
        disponibles dans Iris. Contactez un responsable pour les activer.
      </p>
    );
  } else {
    body = (
      <>
        <p className="hp-extra-status" role="status">
          {subscribed
            ? "Les notifications sont activées sur cet appareil."
            : permission === "denied"
              ? "Les notifications sont bloquées pour ce site dans votre navigateur."
              : "Les notifications ne sont pas activées sur cet appareil."}
        </p>
        <div className="hp-button-row">
          {subscribed ? (
            <>
              <button type="button" className="hp-outline-button" onClick={sendTest} disabled={busy}>
                Envoyer un test
              </button>
              <button type="button" className="hp-outline-button" onClick={deactivate} disabled={busy}>
                Désactiver sur cet appareil
              </button>
            </>
          ) : (
            <button
              type="button"
              className="hp-save-button"
              onClick={activate}
              disabled={busy || permission === "denied"}
            >
              {busy ? (
                <LoaderCircle className="hp-spin" size={17} aria-hidden="true" />
              ) : (
                <BellRing size={17} aria-hidden="true" />
              )}
              Activer les notifications
            </button>
          )}
        </div>
        {permission === "denied" && !subscribed && (
          <p className="hp-extra-note">
            Pour les réactiver, autorisez les notifications pour ce site dans les réglages de votre
            navigateur, puis rechargez la page.
          </p>
        )}
      </>
    );
  }

  return (
    <section className="hp-extra-card" aria-labelledby="hp-device-title" data-testid="helper-push-device">
      <header className="hp-extra-header">
        <span className="hp-card-icon">
          <Smartphone size={22} aria-hidden="true" />
        </span>
        <div>
          <p className="hp-eyebrow">CET APPAREIL</p>
          <h2 id="hp-device-title">Notifications sur cet appareil</h2>
        </div>
      </header>
      <div className="hp-extra-body">{body}</div>
    </section>
  );
}

function formatDateTime(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    return false;
  }
}

function AgendaIcsSection() {
  const [status, setStatus] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState("");

  useEffect(() => {
    let active = true;
    api
      .get("/agenda/ics/status")
      .then((response) => {
        if (active) setStatus(response.data);
      })
      .catch((err) => {
        if (!active) return;
        if (err?.response?.status === 403 || err?.response?.status === 401) setHidden(true);
        else setError(getErrorMessage(err));
      });
    return () => {
      active = false;
    };
  }, []);

  if (hidden) return null;

  const generate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const response = await api.post("/agenda/ics/token");
      setFeedUrl(response.data?.url || "");
      setStatus({ enabled: true, created_at: new Date().toISOString() });
      setConfirm("");
      toast.success("Lien d’agenda généré.");
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.delete("/agenda/ics/token");
      setStatus({ enabled: false, created_at: null });
      setFeedUrl("");
      setConfirm("");
      toast.success("Lien d’agenda révoqué.");
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (await copyText(feedUrl)) toast.success("Lien copié.");
    else toast.error("Copie impossible. Sélectionnez le lien et copiez-le manuellement.");
  };

  const webcal = feedUrl.replace(/^https?:/i, "webcal:");

  return (
    <section className="hp-extra-card" aria-labelledby="hp-ics-title" data-testid="helper-agenda-ics">
      <header className="hp-extra-header">
        <span className="hp-card-icon">
          <CalendarDays size={22} aria-hidden="true" />
        </span>
        <div>
          <p className="hp-eyebrow">AGENDA</p>
          <h2 id="hp-ics-title">Agenda sur mon téléphone</h2>
        </div>
      </header>

      <div className="hp-extra-body">
        <p className="hp-extra-note">
          Abonnez Google Agenda ou Apple Calendrier à votre agenda staff : réunions, absences et tâches
          s’y affichent et se mettent à jour automatiquement.
        </p>

        {error ? (
          <p className="hp-extra-note hp-notice" role="alert">{error}</p>
        ) : !status ? (
          <div className="hp-state" role="status">
            <LoaderCircle className="hp-spin" size={20} aria-hidden="true" />
            Chargement…
          </div>
        ) : (
          <>
            <p className="hp-extra-status" role="status">
              {status.enabled
                ? `Un lien d’abonnement est actif${status.created_at ? ` (créé le ${formatDateTime(status.created_at)})` : ""}.`
                : "Aucun lien d’abonnement actif."}
            </p>

            {feedUrl && (
              <div className="hp-feed-box">
                <p className="hp-extra-note hp-notice">
                  Ce lien est personnel et ne sera plus affiché après avoir quitté cette page. Ne le partagez
                  pas : il donne accès à votre agenda.
                </p>
                <label htmlFor="hp-ics-url">Lien d’abonnement</label>
                <input id="hp-ics-url" className="hp-feed-input" readOnly value={feedUrl} onFocus={(e) => e.target.select()} />
                <div className="hp-button-row">
                  <button type="button" className="hp-outline-button" onClick={copy}>
                    <Copy size={16} aria-hidden="true" />
                    Copier le lien
                  </button>
                  <a className="hp-outline-button" href={webcal}>
                    Ouvrir dans mon application d’agenda
                  </a>
                </div>
              </div>
            )}

            <div className="hp-button-row">
              {confirm === "regenerate" ? (
                <span className="hp-confirm" role="group" aria-label="Confirmer la régénération du lien">
                  <span>L’ancien lien cessera de fonctionner.</span>
                  <button type="button" className="hp-save-button" onClick={generate} disabled={busy}>
                    Régénérer
                  </button>
                  <button type="button" className="hp-outline-button" onClick={() => setConfirm("")} disabled={busy}>
                    Annuler
                  </button>
                </span>
              ) : confirm === "revoke" ? (
                <span className="hp-confirm" role="group" aria-label="Confirmer la révocation du lien">
                  <span>Les agendas abonnés ne se mettront plus à jour.</span>
                  <button type="button" className="hp-secondary-button" onClick={revoke} disabled={busy}>
                    Révoquer
                  </button>
                  <button type="button" className="hp-outline-button" onClick={() => setConfirm("")} disabled={busy}>
                    Annuler
                  </button>
                </span>
              ) : status.enabled ? (
                <>
                  <button type="button" className="hp-outline-button" onClick={() => setConfirm("regenerate")} disabled={busy}>
                    Régénérer le lien
                  </button>
                  <button type="button" className="hp-outline-button" onClick={() => setConfirm("revoke")} disabled={busy}>
                    Révoquer
                  </button>
                </>
              ) : (
                <button type="button" className="hp-save-button" onClick={generate} disabled={busy}>
                  {busy && <LoaderCircle className="hp-spin" size={17} aria-hidden="true" />}
                  Générer mon lien
                </button>
              )}
            </div>
          </>
        )}

        <div className="hp-howto">
          <h3>Comment s’abonner</h3>
          <p>
            <strong>Google Agenda</strong> (sur ordinateur) : « Autres agendas », « + », « À partir de
            l’URL », puis collez le lien. Il apparaîtra aussi sur votre téléphone.
          </p>
          <p>
            <strong>Apple Calendrier</strong> : sur iPhone, touchez « Ouvrir dans mon application
            d’agenda ». Sur Mac, menu Fichier, « Nouvel abonnement à un calendrier », puis collez le lien.
          </p>
        </div>
      </div>
    </section>
  );
}

export default function HelperProfilePage({ helper }) {
  const [triggers, setTriggers] = useState("");
  const [savedTriggers, setSavedTriggers] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [avatarError, setAvatarError] = useState(false);

  const pseudo =
    helper?.global_name ||
    helper?.display_name ||
    helper?.username ||
    "Mon compte";

  const hasChanges = triggers !== savedTriggers;

  useEffect(() => {
    document.body.classList.add("profile-no-nav");

    return () => {
      document.body.classList.remove("profile-no-nav");
    };
  }, []);

  useEffect(() => {
    setAvatarError(false);
  }, [helper?.avatar_url]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setLoading(true);
    setLoadError("");

    const loadProfile = async () => {
      try {
        const response = await api.get("/profile/me", {
          signal: controller.signal,
        });

        if (!active) return;

        const value = response.data.triggers || "";
        setTriggers(value);
        setSavedTriggers(value);
      } catch (error) {
        if (!active || controller.signal.aborted) return;

        setLoadError(getErrorMessage(error));
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    loadProfile();

    return () => {
      active = false;
      controller.abort();
    };
  }, [helper?.id, reloadKey]);

  const saveProfile = async (event) => {
    event.preventDefault();

    if (loading || saving || loadError || !hasChanges) return;

    const valueToSave = triggers;

    setSaving(true);

    try {
      await api.put("/profile/me", {
        triggers: valueToSave,
      });

      setSavedTriggers(valueToSave);
      toast.success("Profil enregistré.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="hp-page"
      data-testid="helper-profile-page"
    >
      <header className="hp-header">
        <div>
          <p className="hp-eyebrow">ESPACE PERSONNEL</p>
          <h1>Mon profil</h1>
          <p className="hp-intro">
            Un espace pour préciser vos limites et accompagner
            les membres à votre rythme.
          </p>
        </div>

        <Link to="/" className="hp-home-button">
          Accueil
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </header>

      <div className="hp-layout">
        <aside className="hp-identity-card">
          <span className="hp-avatar">
            {helper?.avatar_url && !avatarError ? (
              <img
                src={helper.avatar_url}
                alt=""
                onError={() => setAvatarError(true)}
              />
            ) : (
              <UserRound size={34} aria-hidden="true" />
            )}
          </span>

          <p className="hp-eyebrow">MON COMPTE DISCORD</p>
          <h2>{pseudo}</h2>

          {helper?.username && (
            <p className="hp-username">@{helper.username}</p>
          )}

          <div className="hp-identity-detail">
            <span>Identifiant Discord</span>
            <code>{helper?.id || "Non disponible"}</code>
          </div>

          <p className="hp-identity-note">
            Votre nom et votre avatar proviennent de votre
            compte Discord.
          </p>
        </aside>

        <section
          className="hp-preferences-card"
          data-testid="helper-triggers-card"
          aria-labelledby="hp-triggers-title"
        >
          <header className="hp-card-header">
            <span className="hp-card-icon">
              <ShieldCheck size={23} aria-hidden="true" />
            </span>

            <div>
              <p className="hp-eyebrow">MES REPÈRES</p>
              <h2 id="hp-triggers-title">
                Mes limites et sujets sensibles
              </h2>
            </div>
          </header>

          {loading ? (
            <div
              className="hp-state"
              role="status"
              data-testid="helper-profile-loading"
            >
              <LoaderCircle
                className="hp-spin"
                size={23}
                aria-hidden="true"
              />
              Chargement du profil…
            </div>
          ) : loadError ? (
            <div className="hp-load-error" role="alert">
              <h3>Le profil n’a pas pu être chargé.</h3>
              <p>{loadError}</p>

              <button
                type="button"
                className="hp-secondary-button"
                onClick={() => setReloadKey((value) => value + 1)}
              >
                Réessayer
              </button>
            </div>
          ) : (
            <form onSubmit={saveProfile} className="hp-form">
              <p className="hp-description" id="hp-triggers-help">
                Indiquez les situations, sujets ou formulations
                qui peuvent être difficiles pour vous.
                Vous pouvez modifier ces informations à tout moment.
              </p>

              <label htmlFor="hp-triggers">
                Mes triggers et points de vigilance
              </label>

              <textarea
                id="hp-triggers"
                value={triggers}
                onChange={(event) =>
                  setTriggers(event.target.value)
                }
                placeholder={
                  "Exemples : certains sujets sensibles, " +
                  "des situations à éviter ou des précautions " +
                  "utiles lors de l’attribution d’un suivi…"
                }
                maxLength={8000}
                rows={9}
                disabled={saving}
                aria-describedby="hp-triggers-help hp-character-count"
                data-testid="helper-triggers-input"
              />

              <div className="hp-field-footer">
                <span className="hp-field-hint">
                  Renseignez uniquement ce que vous souhaitez partager.
                </span>

                <span id="hp-character-count">
                  {triggers.length.toLocaleString("fr-FR")} / 8 000
                </span>
              </div>

              <footer className="hp-save-footer">
                <span
                  className={`hp-save-state ${
                    hasChanges ? "has-changes" : ""
                  }`}
                  role="status"
                >
                  {saving
                    ? "Enregistrement en cours…"
                    : hasChanges
                      ? "Modifications non enregistrées"
                      : "Aucune modification en attente"}
                </span>

                <button
                  className="hp-save-button"
                  type="submit"
                  disabled={saving || !hasChanges}
                  data-testid="save-helper-profile-button"
                >
                  {saving ? (
                    <LoaderCircle
                      className="hp-spin"
                      size={17}
                      aria-hidden="true"
                    />
                  ) : (
                    <Save size={17} aria-hidden="true" />
                  )}

                  {saving ? "Enregistrement…" : "Enregistrer mon profil"}
                </button>
              </footer>
            </form>
          )}
        </section>
      </div>

      <div className="hp-extras">
        <DisplayPrefsSection />
        <NotificationPrefsSection />
        <DevicePushSection />
        <AgendaIcsSection />
      </div>
    </section>
  );
}
