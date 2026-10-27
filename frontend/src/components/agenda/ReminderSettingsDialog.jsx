import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, Hash, Info, LoaderCircle, RefreshCw, Send, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import "@/Agenda.css";

import AgendaDialog from "./AgendaDialog";
import { agendaKeys, agendaQueries, invalidateAgenda, sendSettingsTest, updateSettings } from "./agendaApi";
import { DEFAULT_DAY_REMINDER_TIME } from "./agendaConstants";
import { agendaErrorMessage, splitAgendaError } from "./agendaErrors";
import { isTime } from "./dateUtils";

const DISCORD_ID_RE = /^\d{17,20}$/;
const INVALID_ID_MESSAGE = "Identifiant Discord invalide : 17 à 20 chiffres.";
const SETTINGS_KEYS = ["enabled", "channel_id", "ping_role_id", "day_reminder_time"];

function formFromSettings(settings) {
  return {
    enabled: settings?.enabled !== false,
    channel_id: settings?.channel_id || "",
    ping_role_id: settings?.ping_role_id || "",
    day_reminder_time: isTime(settings?.day_reminder_time) ? settings.day_reminder_time : DEFAULT_DAY_REMINDER_TIME,
  };
}

function cleanId(value) {
  return String(value || "").replace(/\s+/g, "");
}

function validate(form) {
  const errors = {};
  const channel = cleanId(form.channel_id);
  const role = cleanId(form.ping_role_id);
  if (channel && !DISCORD_ID_RE.test(channel)) errors.channel_id = INVALID_ID_MESSAGE;
  if (role && !DISCORD_ID_RE.test(role)) errors.ping_role_id = INVALID_ID_MESSAGE;
  if (!isTime(form.day_reminder_time)) errors.day_reminder_time = "Indiquez une heure au format HH:MM.";
  return errors;
}

function payloadFromForm(form) {
  return {
    enabled: Boolean(form.enabled),
    channel_id: cleanId(form.channel_id) || null,
    ping_role_id: cleanId(form.ping_role_id) || null,
    day_reminder_time: form.day_reminder_time,
  };
}

// Corps du PUT : seulement les champs modifiés (un champ absent reste inchangé côté serveur, et le salon
// n'est revérifié auprès de Discord que s'il change). L'interrupteur n'est jamais envoyé quand
// l'environnement coupe les rappels : sa valeur en base n'est pas connue ici.
function settingsPatch(form, initial, { disabledByEnv = false } = {}) {
  if (!form || !initial) return {};
  const next = payloadFromForm(form);
  const before = payloadFromForm(initial);
  const patch = {};
  for (const key of SETTINGS_KEYS) {
    if (key === "enabled" && disabledByEnv) continue;
    if (next[key] !== before[key]) patch[key] = next[key];
  }
  return patch;
}

function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p className="ag-field-error" id={id}>
      <CircleAlert size={14} aria-hidden="true" />
      {message}
    </p>
  );
}

// État du salon enregistré : nom résolu, inaccessible ou non choisi.
function ChannelStatus({ settings, changed }) {
  if (changed) {
    return (
      <p className="ag-channel-status">
        <Info size={14} aria-hidden="true" />
        Le salon sera vérifié à l'enregistrement.
      </p>
    );
  }
  if (settings?.channel_status === "ok") {
    return (
      <p className="ag-channel-status is-ok">
        <Hash size={14} aria-hidden="true" />
        {settings.channel_name ? `Salon trouvé : #${settings.channel_name}` : "Salon trouvé"}
      </p>
    );
  }
  if (settings?.channel_status === "inaccessible") {
    return (
      <p className="ag-channel-status is-error">
        <TriangleAlert size={14} aria-hidden="true" />
        Salon inaccessible
      </p>
    );
  }
  return (
    <p className="ag-channel-status">
      <Info size={14} aria-hidden="true" />
      Aucun salon choisi : aucun rappel ne part.
    </p>
  );
}

// Réglages des rappels Discord (responsables) : GET/PUT /agenda/settings et message de test.
export default function ReminderSettingsDialog({ open, onOpenChange, onSaved }) {
  const queryClient = useQueryClient();
  const baseId = `ag-settings-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const settingsQuery = useQuery({ ...agendaQueries.settings(), enabled: Boolean(open) });
  const settings = settingsQuery.data || null;

  const [form, setForm] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [testPing, setTestPing] = useState(false);

  useEffect(() => {
    if (!open) {
      setForm(null);
      setFieldErrors({});
      setFormError("");
      setTestPing(false);
      return;
    }
    if (form === null && settings) setForm(formFromSettings(settings));
  }, [open, settings, form]);

  const disabledByEnv = Boolean(settings?.disabled_by_env);
  const initial = useMemo(() => (settings ? formFromSettings(settings) : null), [settings]);
  const patch = useMemo(() => settingsPatch(form, initial, { disabledByEnv }), [form, initial, disabledByEnv]);
  const dirty = Object.keys(patch).length > 0;
  const channelChanged = Boolean(form && settings && cleanId(form.channel_id) !== (settings.channel_id || ""));

  const save = useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(agendaKeys.settings, data);
      invalidateAgenda(queryClient);
      toast.success("Réglages des rappels enregistrés.");
      if (onSaved) onSaved(data);
      if (onOpenChange) onOpenChange(false);
    },
    onError: (error) => {
      const { field, message } = splitAgendaError(error);
      if (field === "channel_id" || field === "ping_role_id" || field === "day_reminder_time") {
        setFieldErrors({ [field]: message });
        setFormError("");
      } else {
        setFormError(message);
      }
    },
  });

  const test = useMutation({
    mutationFn: sendSettingsTest,
    onSuccess: () => {
      const name = settings?.channel_name ? `#${settings.channel_name}` : "le salon des rappels";
      setFormError("");
      toast.success(`Message de test envoyé dans ${name}.`);
    },
    onError: (error) => {
      const message = agendaErrorMessage(error);
      setFormError(`Message de test : ${message}`);
      toast.error(message);
    },
  });

  const update = (key, value) => {
    setForm((previous) => ({ ...(previous || formFromSettings(settings)), [key]: value }));
    setFieldErrors((previous) => (previous[key] ? { ...previous, [key]: undefined } : previous));
  };

  const handleSubmit = () => {
    if (!form || save.isPending) return;
    const errors = validate(form);
    setFieldErrors(errors);
    if (Object.values(errors).some(Boolean)) {
      setFormError("");
      return;
    }
    setFormError("");
    if (!dirty) {
      if (onOpenChange) onOpenChange(false);
      return;
    }
    save.mutate(patch);
  };

  const busy = save.isPending || test.isPending;
  const hasSavedChannel = Boolean(settings?.channel_id) || settings?.channel_status === "ok";
  const testBlocked = !settings || disabledByEnv || !hasSavedChannel || dirty;
  const testHelp = !settings
    ? ""
    : disabledByEnv
      ? "Impossible d'envoyer un test : les rappels sont désactivés par la configuration du serveur."
      : !hasSavedChannel
        ? "Choisissez un salon et enregistrez avant d'envoyer un test."
        : dirty
          ? "Enregistrez d'abord : le test utilise les réglages enregistrés."
          : "";

  const footer = (
    <>
      <div className="ag-dialog-footer-start">
        <button
          type="button"
          className="ag-button ag-button--secondary"
          onClick={() => test.mutate({ ping: testPing && Boolean(settings?.ping_role_id) })}
          disabled={testBlocked || busy}
          aria-describedby={testHelp ? `${baseId}-test-help` : undefined}
        >
          {test.isPending ? (
            <LoaderCircle size={15} className="ag-spin" aria-hidden="true" />
          ) : (
            <Send size={15} aria-hidden="true" />
          )}
          Envoyer un message de test
        </button>
      </div>
      <div className="ag-dialog-footer-end">
        <button
          type="button"
          className="ag-button ag-button--secondary"
          onClick={() => onOpenChange && onOpenChange(false)}
          disabled={save.isPending}
        >
          Annuler
        </button>
        <button type="submit" className="ag-button" disabled={!form || busy}>
          {save.isPending ? (
            <LoaderCircle size={15} className="ag-spin" aria-hidden="true" />
          ) : (
            <Check size={15} aria-hidden="true" />
          )}
          Enregistrer
        </button>
      </div>
    </>
  );

  let body;
  if (settingsQuery.isError && !settings) {
    body = (
      <div className="ag-error" role="alert">
        <span className="ag-error-text">
          <CircleAlert size={15} aria-hidden="true" />
          {agendaErrorMessage(settingsQuery.error, "Impossible de charger les réglages.")}
        </span>
        <button
          type="button"
          className="ag-error-retry"
          onClick={() => settingsQuery.refetch()}
          disabled={settingsQuery.isFetching}
        >
          <RefreshCw size={13} aria-hidden="true" className={settingsQuery.isFetching ? "ag-spin" : undefined} />
          Réessayer
        </button>
      </div>
    );
  } else if (!form) {
    body = (
      <div className="ag-skeleton-stack" aria-hidden="true">
        <span className="ag-skeleton ag-skeleton-line" style={{ width: "45%" }} />
        <span className="ag-skeleton" style={{ height: 44 }} />
        <span className="ag-skeleton ag-skeleton-line" style={{ width: "60%" }} />
        <span className="ag-skeleton" style={{ height: 44 }} />
        <span className="ag-skeleton" style={{ height: 44 }} />
      </div>
    );
  } else {
    body = (
      <div className="ag-form ag-settings-form">
        {formError ? (
          <p className="ag-error" role="alert">
            <span className="ag-error-text">
              <CircleAlert size={15} aria-hidden="true" />
              {formError}
            </span>
          </p>
        ) : null}

        {disabledByEnv ? (
          <p className="ag-callout ag-callout--warning">
            <TriangleAlert size={15} aria-hidden="true" />
            <span>Les rappels sont désactivés par la configuration du serveur (AGENDA_REMINDERS_ENABLED).</span>
          </p>
        ) : null}

        <label className={`ag-switch${disabledByEnv ? " is-disabled" : ""}`} htmlFor={`${baseId}-enabled`}>
          <input
            id={`${baseId}-enabled`}
            type="checkbox"
            role="switch"
            className="ag-check-input"
            checked={disabledByEnv ? false : form.enabled}
            disabled={disabledByEnv}
            onChange={(event) => update("enabled", event.target.checked)}
          />
          <span className="ag-switch-track" aria-hidden="true" />
          <span className="ag-switch-label">Activer les rappels Discord</span>
        </label>

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-channel`}>
            Identifiant du salon
          </label>
          <input
            id={`${baseId}-channel`}
            className="ag-input"
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
            maxLength={24}
            placeholder="123456789012345678"
            value={form.channel_id}
            onChange={(event) => update("channel_id", event.target.value)}
            aria-invalid={fieldErrors.channel_id ? "true" : undefined}
            aria-describedby={`${baseId}-channel-help${fieldErrors.channel_id ? ` ${baseId}-channel-error` : ""}`}
          />
          <p className="ag-help" id={`${baseId}-channel-help`}>
            Dans Discord : clic droit sur le salon &gt; Copier l'identifiant (mode développeur activé).
          </p>
          <FieldError id={`${baseId}-channel-error`} message={fieldErrors.channel_id} />
          <ChannelStatus settings={settings} changed={channelChanged} />
        </div>

        {!channelChanged && settings?.channel_status === "ok" && settings.channel_visibility === "public" ? (
          <p className="ag-callout ag-callout--warning">
            <TriangleAlert size={15} aria-hidden="true" />
            <span>
              Ce salon semble visible par tous les membres du serveur. Les rappels contiennent l'ordre du jour des
              réunions et la description des entrées : utilisez un salon réservé au staff.
            </span>
          </p>
        ) : null}
        {!channelChanged && settings?.channel_status === "ok" && settings.channel_visibility === "inconnu" ? (
          <p className="ag-callout">
            <Info size={15} aria-hidden="true" />
            <span>Impossible de vérifier qui voit ce salon.</span>
          </p>
        ) : null}

        <div className="ag-field">
          <label className="ag-label" htmlFor={`${baseId}-role`}>
            Identifiant du rôle à mentionner <span className="ag-label-optional">(facultatif)</span>
          </label>
          <input
            id={`${baseId}-role`}
            className="ag-input"
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
            maxLength={24}
            placeholder="234567890123456789"
            value={form.ping_role_id}
            onChange={(event) => update("ping_role_id", event.target.value)}
            aria-invalid={fieldErrors.ping_role_id ? "true" : undefined}
            aria-describedby={fieldErrors.ping_role_id ? `${baseId}-role-error` : undefined}
          />
          <FieldError id={`${baseId}-role-error`} message={fieldErrors.ping_role_id} />
        </div>

        <div className="ag-field ag-settings-time">
          <label className="ag-label" htmlFor={`${baseId}-time`}>
            Heure des rappels pour les éléments sur la journée
          </label>
          <input
            id={`${baseId}-time`}
            type="time"
            className="ag-input"
            step={300}
            value={form.day_reminder_time}
            onChange={(event) => update("day_reminder_time", event.target.value)}
            aria-invalid={fieldErrors.day_reminder_time ? "true" : undefined}
            aria-describedby={`${baseId}-time-help${fieldErrors.day_reminder_time ? ` ${baseId}-time-error` : ""}`}
          />
          <p className="ag-help" id={`${baseId}-time-help`}>
            Heure de Paris. Utilisée aussi pour les réunions sans heure.
          </p>
          <FieldError id={`${baseId}-time-error`} message={fieldErrors.day_reminder_time} />
        </div>

        {settings?.ping_role_id ? (
          <label className="ag-checkbox" htmlFor={`${baseId}-test-ping`}>
            <input
              id={`${baseId}-test-ping`}
              type="checkbox"
              className="ag-check-input"
              checked={testPing}
              onChange={(event) => setTestPing(event.target.checked)}
            />
            <span className="ag-check-mark" aria-hidden="true">
              <Check size={12} strokeWidth={3} />
            </span>
            <span className="ag-check-text">Mentionner le rôle dans le message de test</span>
          </label>
        ) : null}

        {testHelp ? (
          <p className="ag-help" id={`${baseId}-test-help`}>
            {testHelp}
          </p>
        ) : null}

        {settings?.source === "env" ? (
          <p className="ag-help">Valeurs reprises de la configuration du serveur tant que rien n'est enregistré ici.</p>
        ) : null}
      </div>
    );
  }

  return (
    <AgendaDialog
      open={open}
      onOpenChange={onOpenChange}
      eyebrow="Responsables"
      title="Réglages des rappels Discord"
      description="Salon, rôle mentionné et heure des rappels envoyés par Iris."
      footer={footer}
      note="Les rappels partent 7 jours, 2 jours, 1 jour et 1 heure avant, à l'heure de Paris. Jamais pour les absences."
      onSubmit={handleSubmit}
      dismissible={!save.isPending}
      busy={busy || settingsQuery.isPending}
    >
      {body}
    </AgendaDialog>
  );
}

export { ReminderSettingsDialog };
