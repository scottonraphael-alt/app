import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

import { api, getErrorMessage } from "../api/client";
import "../components/responsable/Responsable.css";

const ROLES = [
  ["helper", "Helpers"],
  ["staff", "Staff"],
  ["admin", "Coordinateurs"],
  ["responsable", "Responsables"],
  ["operateur", "Opérateurs"],
  ["animateur", "Animateurs"],
];
const LEVELS = [
  ["info", "Information"],
  ["succes", "Succès"],
  ["alerte", "Alerte"],
  ["critique", "Critique"],
];

const toLocalInput = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const fromLocalInput = (value) => (value ? new Date(value).toISOString() : null);

/* ---------- Attribution et SLA ---------- */
function RoutingCard() {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/routing/settings").then((r) => setForm(r.data)).catch((e) => setError(getErrorMessage(e)));
  }, []);

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const r = await api.put("/routing/settings", {
        auto_assign_enabled: !!form.auto_assign_enabled,
        first_response_minutes: Number(form.first_response_minutes),
        escalate_after_minutes: Number(form.escalate_after_minutes),
      });
      setForm(r.data);
      toast.success("Réglages d’attribution enregistrés.");
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="rs-card">
      <h2>Attribution et délais de réponse</h2>
      <p className="rs-card-hint">Attribution automatique des tickets et seuils du délai de première réponse (SLA).</p>
      {!form && !error && <p className="rs-muted" role="status">Chargement…</p>}
      {form && (
        <form onSubmit={save}>
          <label className="rs-check">
            <input
              type="checkbox"
              checked={!!form.auto_assign_enabled}
              onChange={(e) => setForm({ ...form, auto_assign_enabled: e.target.checked })}
            />
            Attribuer automatiquement les nouveaux tickets
          </label>
          <div className="rs-row">
            <div className="rs-field">
              <label htmlFor="rs-first">Première réponse (minutes)</label>
              <input id="rs-first" type="number" min="1" max="1440" required value={form.first_response_minutes}
                onChange={(e) => setForm({ ...form, first_response_minutes: e.target.value })} />
            </div>
            <div className="rs-field">
              <label htmlFor="rs-esc">Escalade après (minutes)</label>
              <input id="rs-esc" type="number" min="1" max="10080" required value={form.escalate_after_minutes}
                onChange={(e) => setForm({ ...form, escalate_after_minutes: e.target.value })} />
            </div>
          </div>
          {error && <p className="rs-error" role="alert">{error}</p>}
          <div className="rs-footer">
            <button type="submit" className="rs-btn rs-btn-primary" disabled={saving}>{saving ? "Enregistrement…" : "Enregistrer"}</button>
          </div>
        </form>
      )}
      {!form && error && <p className="rs-error" role="alert">{error}</p>}
    </article>
  );
}

/* ---------- Rappels agenda ---------- */
function AgendaCard() {
  const [form, setForm] = useState(null);
  const [info, setInfo] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  const apply = (data) => {
    setInfo(data);
    setForm({
      enabled: !!data.enabled,
      channel_id: data.channel_id || "",
      ping_role_id: data.ping_role_id || "",
      day_reminder_time: data.day_reminder_time || "10:00",
    });
  };

  useEffect(() => {
    api.get("/agenda/settings").then((r) => apply(r.data)).catch((e) => setError(getErrorMessage(e)));
  }, []);

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const r = await api.put("/agenda/settings", {
        enabled: form.enabled,
        channel_id: form.channel_id.trim() || null,
        ping_role_id: form.ping_role_id.trim() || null,
        day_reminder_time: form.day_reminder_time || null,
      });
      apply(r.data);
      toast.success("Réglages des rappels enregistrés.");
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      await api.post("/agenda/settings/test", { ping: false });
      toast.success("Message de test envoyé.");
    } catch (e) {
      toast.error(getErrorMessage(e));
    } finally {
      setTesting(false);
    }
  };

  return (
    <article className="rs-card">
      <h2>
        Rappels de l’agenda
        {info && (
          <span className={`rs-pill ${info.configured ? "rs-pill-ok" : "rs-pill-warn"}`}>
            {info.configured ? "Actifs" : "Inactifs"}
          </span>
        )}
      </h2>
      <p className="rs-card-hint">Salon Discord, rôle mentionné et heure des rappels « journée entière ».</p>
      {!form && !error && <p className="rs-muted" role="status">Chargement…</p>}
      {form && (
        <form onSubmit={save}>
          {info?.disabled_by_env && (
            <p className="rs-muted">L’envoi est désactivé par la configuration du serveur et ne peut pas être réactivé ici.</p>
          )}
          <label className="rs-check">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
            Envoyer les rappels sur Discord
          </label>
          <div className="rs-field">
            <label htmlFor="rs-channel">Identifiant du salon</label>
            <input id="rs-channel" type="text" inputMode="numeric" value={form.channel_id}
              onChange={(e) => setForm({ ...form, channel_id: e.target.value })} />
            {info?.channel_name && <span className="rs-muted">Salon : #{info.channel_name}</span>}
          </div>
          <div className="rs-row">
            <div className="rs-field">
              <label htmlFor="rs-role">Rôle à mentionner</label>
              <input id="rs-role" type="text" inputMode="numeric" value={form.ping_role_id}
                onChange={(e) => setForm({ ...form, ping_role_id: e.target.value })} />
            </div>
            <div className="rs-field">
              <label htmlFor="rs-time">Heure des rappels « journée »</label>
              <input id="rs-time" type="time" value={form.day_reminder_time}
                onChange={(e) => setForm({ ...form, day_reminder_time: e.target.value })} />
            </div>
          </div>
          {error && <p className="rs-error" role="alert">{error}</p>}
          <div className="rs-footer">
            <button type="submit" className="rs-btn rs-btn-primary" disabled={saving}>{saving ? "Enregistrement…" : "Enregistrer"}</button>
            <button type="button" className="rs-btn" onClick={test} disabled={testing || !info?.configured}>
              {testing ? "Envoi…" : "Envoyer un test"}
            </button>
          </div>
        </form>
      )}
      {!form && error && <p className="rs-error" role="alert">{error}</p>}
    </article>
  );
}

/* ---------- Intégrations ---------- */
function IntegrationsCard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/system-health/integrations").then((r) => setData(r.data)).catch((e) => setError(getErrorMessage(e)));
  }, []);

  const row = (label, ok, hint) => (
    <li>
      <div className="rs-list-head">
        <strong>{label}</strong>
        <span className={`rs-pill ${ok ? "rs-pill-ok" : "rs-pill-warn"}`}>{ok ? "Configuré" : "Non configuré"}</span>
      </div>
      <span className="rs-muted">{hint}</span>
    </li>
  );

  return (
    <article className="rs-card">
      <h2>Notifications push et IA</h2>
      <p className="rs-card-hint">Ces intégrations dépendent des variables d’environnement du serveur ; seul leur état est affiché.</p>
      {error && <p className="rs-error" role="alert">{error}</p>}
      {!data && !error && <p className="rs-muted" role="status">Chargement…</p>}
      {data && (
        <ul className="rs-list">
          {row("Notifications push", data.push_configured, "Clés VAPID du serveur.")}
          {row("Assistance IA", data.ai_configured, "Clé Anthropic du serveur (résumés, copilote, détection de crise).")}
        </ul>
      )}
    </article>
  );
}

/* ---------- Annonces internes ---------- */
const EMPTY = { message: "", level: "info", starts_at: "", ends_at: "", roles: [], active: true };

function AnnouncementsCard() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/staff-announcements");
      setItems(r.data.items || []);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const reset = () => {
    setForm(EMPTY);
    setEditId(null);
    setError("");
  };

  const edit = (item) => {
    setEditId(item.id);
    setForm({
      message: item.message,
      level: item.level,
      starts_at: toLocalInput(item.starts_at),
      ends_at: toLocalInput(item.ends_at),
      roles: item.roles || [],
      active: item.active,
    });
  };

  const toggleRole = (role) =>
    setForm((f) => ({ ...f, roles: f.roles.includes(role) ? f.roles.filter((x) => x !== role) : [...f.roles, role] }));

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload = {
      message: form.message,
      level: form.level,
      starts_at: fromLocalInput(form.starts_at),
      ends_at: fromLocalInput(form.ends_at),
      roles: form.roles,
      active: form.active,
    };
    try {
      if (editId) await api.patch(`/staff-announcements/${editId}`, payload);
      else await api.post("/staff-announcements", payload);
      toast.success(editId ? "Annonce modifiée." : "Annonce publiée.");
      reset();
      load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(Array.isArray(detail) ? "Vérifiez le message et les dates." : getErrorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item) => {
    if (!window.confirm("Supprimer cette annonce ?")) return;
    try {
      await api.delete(`/staff-announcements/${item.id}`);
      toast.success("Annonce supprimée.");
      if (editId === item.id) reset();
      load();
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  };

  return (
    <article className="rs-card rs-card-wide">
      <h2>Bandeau d’annonce interne</h2>
      <p className="rs-card-hint">
        Message affiché en haut d’Iris pour le staff ciblé, fermable par chaque personne. Sans rôle coché, tout le monde le voit.
      </p>
      <form onSubmit={submit}>
        <div className="rs-field">
          <label htmlFor="rs-msg">Message (500 caractères au plus)</label>
          <textarea id="rs-msg" required maxLength={500} value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })} />
        </div>
        <div className="rs-row">
          <div className="rs-field">
            <label htmlFor="rs-level">Niveau</label>
            <select id="rs-level" value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })}>
              {LEVELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          <div className="rs-field">
            <label htmlFor="rs-start">Début (facultatif)</label>
            <input id="rs-start" type="datetime-local" value={form.starts_at}
              onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
          </div>
          <div className="rs-field">
            <label htmlFor="rs-end">Fin (facultatif)</label>
            <input id="rs-end" type="datetime-local" value={form.ends_at}
              onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
          </div>
        </div>
        <fieldset className="rs-roles">
          <legend className="rs-muted">Ciblage par rôle</legend>
          {ROLES.map(([key, label]) => (
            <label className="rs-check" key={key} style={{ marginBottom: 0 }}>
              <input type="checkbox" checked={form.roles.includes(key)} onChange={() => toggleRole(key)} />
              {label}
            </label>
          ))}
        </fieldset>
        <label className="rs-check">
          <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
          Active
        </label>
        {error && <p className="rs-error" role="alert">{error}</p>}
        <div className="rs-footer">
          <button type="submit" className="rs-btn rs-btn-primary" disabled={saving}>
            {saving ? "Enregistrement…" : editId ? "Modifier l’annonce" : "Publier l’annonce"}
          </button>
          {editId && <button type="button" className="rs-btn" onClick={reset}>Annuler</button>}
        </div>
      </form>

      {items.length > 0 && (
        <ul className="rs-list" style={{ marginTop: 20 }} aria-label="Annonces existantes">
          {items.map((item) => (
            <li key={item.id}>
              <div className="rs-list-head">
                <span>
                  <span className={`rs-pill ${item.live ? "rs-pill-ok" : ""}`}>{item.live ? "En ligne" : "Hors ligne"}</span>{" "}
                  <span className="rs-pill rs-pill-info">{LEVELS.find(([k]) => k === item.level)?.[1]}</span>
                </span>
                <span className="rs-footer" style={{ margin: 0 }}>
                  <button type="button" className="rs-btn" onClick={() => edit(item)}>Modifier</button>
                  <button type="button" className="rs-btn rs-btn-danger" onClick={() => remove(item)}>Supprimer</button>
                </span>
              </div>
              <p style={{ margin: "8px 0 0", overflowWrap: "anywhere" }}>{item.message}</p>
              <span className="rs-muted">
                {item.roles.length ? `Ciblage : ${item.roles.join(", ")}` : "Tout le staff"}
                {item.ends_at ? ` · jusqu’au ${new Date(item.ends_at).toLocaleString("fr-FR", { timeZone: "Europe/Paris" })}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export default function SettingsPage() {
  useEffect(() => {
    document.body.classList.add("rs-no-nav");
    return () => document.body.classList.remove("rs-no-nav");
  }, []);

  return (
    <section className="rs-page" data-testid="settings-page">
      <header className="rs-header">
        <div className="rs-header-copy">
          <p className="rs-eyebrow">ESPACE RESPONSABLE · RÉGLAGES</p>
          <h1>Réglages</h1>
          <p className="rs-intro">Tous les réglages d’Iris réservés aux responsables, au même endroit.</p>
        </div>
        <div className="rs-actions">
          <Link to="/" className="rs-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>
      <div className="rs-grid">
        <RoutingCard />
        <AgendaCard />
        <IntegrationsCard />
        <AnnouncementsCard />
      </div>
    </section>
  );
}
