import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Archive,
  Calendar,
  ChevronDown,
  Plus,
  Star,
  Trash2,
  UserMinus,
  UserPlus,
  X,
} from "lucide-react";
import { api, getErrorMessage } from "../api/client";

/* ---------------------------------------------------------------------- */
/* Helpers                                                                 */
/* ---------------------------------------------------------------------- */

function normalizeText(value) {
  return (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function isIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || "");
}

function formatDate(value) {
  if (!isIsoDate(value)) return value;
  return new Date(value).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

const ROLE_LABELS = {
  tous: "Tous",
  staff: "Staff",
  helper: "Helper",
};

/* Statut visuel calculé à partir du nombre de volontaires,
   pour donner une bordure colorée type "casier" à chaque tâche. */
function taskAccent(task) {
  if (task.volunteers.length === 0) return "task-accent-open";
  return "task-accent-taken";
}

/* ---------------------------------------------------------------------- */
/* Avatar rond, même logique que moderation-avatar du casier              */
/* ---------------------------------------------------------------------- */

function TaskAvatar({ member, size = 28 }) {
  const [imageError, setImageError] = useState(false);
  const label = member?.display_name || member?.username || "?";

  return (
    <span
      className="task-avatar"
      style={{ width: size, height: size }}
      title={label}
      aria-label={label}
    >
      {member?.avatar_url && !imageError ? (
        <img
          src={member.avatar_url}
          alt=""
          onError={() => setImageError(true)}
        />
      ) : (
        <span className="task-avatar-fallback" style={{ fontSize: size * 0.42 }}>
          {label.charAt(0).toUpperCase()}
        </span>
      )}
    </span>
  );
}

/* ---------------------------------------------------------------------- */
/* Sélection pour nommer un volontaire                                     */
/* ---------------------------------------------------------------------- */

function NominateSelect({ task, members, onNominate }) {
  const [selected, setSelected] = useState("");
  const available = members.filter(
    (m) => !task.volunteers.some((v) => v.id === m.id)
  );

  const handleNominate = async () => {
    if (!selected) return;
    await onNominate(task.id, selected);
    setSelected("");
  };

  if (available.length === 0) return null;

  return (
    <div style={{ display: "flex", gap: "6px" }}>
      <select
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        className="meeting-inline-input"
        style={{ padding: "6px 10px", width: 180 }}
      >
        <option value="">Nommer un membre</option>
        {available.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name || m.username}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn-ghost"
        onClick={handleNominate}
        disabled={!selected}
        style={{ padding: "6px 12px" }}
      >
        <UserPlus size={14} />
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Badge volontaire (avec notation)                                        */
/* ---------------------------------------------------------------------- */

function VolunteerBadge({ volunteer, taskId, isResponsable, onRate, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [rating, setRating] = useState(volunteer.rating || 0);
  const [note, setNote] = useState(volunteer.note || "");

  const save = async () => {
    await onRate(taskId, volunteer.id, rating, note);
    setEditing(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
        <TaskAvatar member={volunteer} size={24} />
        <span className="status-badge status-done">
          {volunteer.display_name || volunteer.username}
          {volunteer.rating ? ` · ${volunteer.rating}/5` : ""}
        </span>
        {isResponsable && (
          <>
            <button
              type="button"
              className="icon-btn-danger"
              onClick={() => setEditing((c) => !c)}
              aria-label="Noter"
              style={{ padding: "4px" }}
            >
              <Star size={14} />
            </button>
            <button
              type="button"
              className="icon-btn-danger"
              onClick={() => onRemove(taskId, volunteer.id)}
              aria-label="Retirer"
              style={{ padding: "4px" }}
            >
              <X size={14} />
            </button>
          </>
        )}
      </div>
      {editing && (
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <select
            value={rating}
            onChange={(e) => setRating(Number(e.target.value))}
            className="meeting-inline-input"
            style={{ width: 70, padding: "4px 6px" }}
          >
            <option value={0}>—</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}/5
              </option>
            ))}
          </select>
          <input
            className="meeting-inline-input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note / commentaire"
            style={{ flex: 1, padding: "4px 8px" }}
          />
          <button
            type="button"
            className="btn-ghost"
            onClick={save}
            style={{ padding: "4px 10px" }}
          >
            OK
          </button>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Carte de tâche                                                          */
/* ---------------------------------------------------------------------- */

function TaskCard({
  task,
  isResponsable,
  members,
  onRemove,
  onToggleSignup,
  isSignedUp,
  onRateVolunteer,
  onRemoveVolunteer,
  onNominate,
}) {
  return (
    <div
  className="meeting-row task-card"
  style={{ flexDirection: "column", alignItems: "stretch", gap: "10px" }}
>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            <span className="category-badge">{task.category}</span>
            {task.target_role && task.target_role !== "tous" && (
              <span className="status-badge">{ROLE_LABELS[task.target_role] || task.target_role}</span>
            )}
          </div>
          <div style={{ fontWeight: 700, fontSize: "20px", marginTop: "8px", color: "var(--ink)" }}>
            {task.name}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
            <Calendar size={14} />
            <span>
              {task.end_date
                ? `${formatDate(task.task_date)} → ${formatDate(task.end_date)}`
                : formatDate(task.task_date)}
            </span>
          </div>
        </div>
        {isResponsable && (
          <button
            type="button"
            className="icon-btn-danger"
            onClick={() => onRemove(task.id)}
            aria-label="Supprimer"
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>

      {task.explanation && (
        <p style={{ fontSize: "13px", color: "var(--muted)", margin: 0, lineHeight: 1.6, wordBreak: "break-word", overflowWrap: "anywhere" }}>
          {task.explanation}
        </p>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginTop: "6px", flexWrap: "wrap", gap: "10px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: 1 }}>
          {task.volunteers.length === 0 ? (
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>Personne inscrit pour l'instant.</span>
          ) : (
            task.volunteers.map((v) => (
              <VolunteerBadge
                key={v.id}
                volunteer={v}
                taskId={task.id}
                isResponsable={isResponsable}
                onRate={onRateVolunteer}
                onRemove={onRemoveVolunteer}
              />
            ))
          )}
          {isResponsable && members && (
            <NominateSelect task={task} members={members} onNominate={onNominate} />
          )}
        </div>

        <button
          type="button"
          className={`btn-ghost ${isSignedUp ? "btn-locked" : ""}`}
          onClick={() => onToggleSignup(task)}
        >
          {isSignedUp ? <UserMinus size={16} /> : <UserPlus size={16} />}
          {isSignedUp ? "Se désinscrire" : "S'inscrire"}
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Ligne de période archivée                                              */
/* ---------------------------------------------------------------------- */

function ArchivedPeriodRow({ period, isOpen, onToggle, isResponsable, onDelete }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (tasks.length > 0) return;
    setLoading(true);
    try {
      const response = await api.get("/staff/tasks", { params: { period_id: period.id } });
      setTasks(response.data);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ borderBottom: "1px solid var(--line)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <button
          type="button"
          onClick={() => {
            onToggle(period.id);
            load();
          }}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flex: 1,
            padding: "16px 24px",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          <span style={{ fontWeight: 600, fontSize: "14px", color: "var(--ink)" }}>
            {formatDate(period.start_date)} → {formatDate(period.end_date)}
          </span>
          <ChevronDown
            size={16}
            style={{ transform: isOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s ease" }}
          />
        </button>
        {isResponsable && (
          <button
            type="button"
            className="icon-btn-danger"
            onClick={() => onDelete(period.id)}
            aria-label="Supprimer la période"
            style={{ marginRight: "16px" }}
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>
      {isOpen && (
        <div style={{ padding: "0 24px 20px" }}>
          {loading ? (
            <p className="dashboard-loading">Chargement…</p>
          ) : tasks.length === 0 ? (
            <p className="dashboard-empty">Aucune tâche enregistrée pour cette période.</p>
          ) : (
            <div className="meeting-list" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {tasks.map((task) => (
                <TaskCard key={task.id} task={task} isResponsable={false} isSignedUp={false} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Page principale                                                        */
/* ---------------------------------------------------------------------- */

export default function QuarterlyTasksPage({ isResponsable, helper }) {
  const [period, setPeriod] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [archivedPeriods, setArchivedPeriods] = useState([]);
  const [openArchiveId, setOpenArchiveId] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [periodStart, setPeriodStart] = useState(new Date().toISOString().slice(0, 10));
  const [creatingPeriod, setCreatingPeriod] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [explanation, setExplanation] = useState("");
  const [taskDate, setTaskDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [targetRole, setTargetRole] = useState("tous");
  const [submitting, setSubmitting] = useState(false);
  const [roleFilter, setRoleFilter] = useState("tous");

  const normalizedCategory = normalizeText(category.trim());
  const isEvent = normalizedCategory.includes("event");
  const isRedactionnel = normalizedCategory.includes("redactionnel");

  const load = async () => {
    setLoading(true);
    try {
      const [periodResponse, archivedResponse] = await Promise.all([
        api.get("/staff/tasks/period"),
        api.get("/staff/tasks/periods/archived"),
      ]);
      setPeriod(periodResponse.data);
      setArchivedPeriods(archivedResponse.data);
      if (periodResponse.data) {
        const tasksResponse = await api.get("/staff/tasks", {
          params: { period_id: periodResponse.data.id },
        });
        setTasks(tasksResponse.data);
      } else {
        setTasks([]);
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (isResponsable) {
      api
        .get("/staff/members")
        .then((res) => setMembers(res.data))
        .catch(() => {});
    }
  }, [isResponsable]);

  const declarePeriod = async (event) => {
    event.preventDefault();
    setCreatingPeriod(true);
    try {
      const response = await api.post("/staff/tasks/period", { start_date: periodStart });
      setPeriod(response.data);
      setTasks([]);
      toast.success("Période déclarée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreatingPeriod(false);
    }
  };

  const archivePeriod = async () => {
    if (!period) return;
    setArchiving(true);
    try {
      await api.post(`/staff/tasks/period/${period.id}/archive`);
      toast.success("Période archivée.");
      await load();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setArchiving(false);
    }
  };

  const removePeriod = async (periodId) => {
    try {
      await api.delete(`/staff/tasks/period/${periodId}`);
      setArchivedPeriods((current) => current.filter((p) => p.id !== periodId));
      if (openArchiveId === periodId) setOpenArchiveId(null);
      toast.success("Période supprimée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const addTask = async (event) => {
    event.preventDefault();
    if (!name.trim() || !category.trim() || !taskDate.trim()) return;
    if (isEvent && !isRedactionnel && !endDate) {
      toast.error("Merci d'indiquer une date de fin pour cet événement.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.post("/staff/tasks", {
        period_id: period.id,
        name,
        category,
        explanation,
        task_date: taskDate,
        end_date: isEvent && !isRedactionnel ? endDate : null,
        target_role: targetRole,
      });
      setTasks((current) => [...current, response.data]);
      setName("");
      setCategory("");
      setExplanation("");
      setTargetRole("tous");
      toast.success("Tâche ajoutée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const removeTask = async (taskId) => {
    try {
      await api.delete(`/staff/tasks/${taskId}`);
      setTasks((current) => current.filter((task) => task.id !== taskId));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const toggleSignup = async (task) => {
    try {
      const response = await api.post(`/staff/tasks/${task.id}/signup`);
      setTasks((current) => current.map((item) => (item.id === task.id ? response.data : item)));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const rateVolunteer = async (taskId, helperId, rating, note) => {
    try {
      const response = await api.put(`/staff/tasks/${taskId}/volunteers/${helperId}/rate`, {
        rating,
        note,
      });
      setTasks((current) => current.map((item) => (item.id === taskId ? response.data : item)));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const removeVolunteer = async (taskId, helperId) => {
    try {
      const response = await api.delete(`/staff/tasks/${taskId}/volunteers/${helperId}`);
      setTasks((current) => current.map((item) => (item.id === taskId ? response.data : item)));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const nominateVolunteer = async (taskId, helperId) => {
    try {
      const response = await api.post(`/staff/tasks/${taskId}/nominate/${helperId}`);
      setTasks((current) => current.map((item) => (item.id === taskId ? response.data : item)));
      toast.success("Membre nommé à la tâche.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const isSignedUp = (task) => helper && task.volunteers.some((v) => v.id === helper.id);

  const filteredTasks = tasks.filter(
    (task) => roleFilter === "tous" || task.target_role === roleFilter || !task.target_role
  );

  return (
    <section className="page-content dashboard-page" data-testid="quarterly-tasks-page">
      <style>{`
        .task-avatar {
          border-radius: 50%;
          overflow: hidden;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          background: var(--line, #e5e7eb);
          flex-shrink: 0;
        }
        .task-avatar img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          border-radius: 50%;
        }
        .task-avatar-fallback {
          font-weight: 600;
          color: var(--muted, #64748b);
        }
        .task-card { border-left: 4px solid transparent; }
        .task-accent-open { border-left-color: #cbd5e1; }
        .task-accent-taken { border-left-color: #34d399; }
      `}</style>

      <header className="page-header">
        <div>
          <p className="eyebrow">ESPACE STAFF</p>
          <h1>Tâches trimestrielles</h1>
        </div>
        {isResponsable && period && (
          <div className="dashboard-actions">
            <button type="button" className="btn-ghost" onClick={archivePeriod} disabled={archiving}>
              <Archive size={16} />
              {archiving ? "Archivage…" : "Archiver la période"}
            </button>
          </div>
        )}
      </header>

      {loading ? (
        <p className="dashboard-loading">Chargement…</p>
      ) : period ? (
        <div className="lock-banner" style={{ background: "#e8efea", color: "#365443" }}>
          <Calendar size={14} />
          <span>
            Période en cours : {formatDate(period.start_date)} → {formatDate(period.end_date)}
          </span>
        </div>
      ) : (
        <p className="dashboard-empty">Aucune période déclarée pour l'instant.</p>
      )}

      {isResponsable && !period && (
        <form onSubmit={declarePeriod} className="meeting-inline-form" style={{ marginTop: "16px", marginBottom: "24px" }}>
          <div className="meeting-inline-form-header">
            <span>Déclarer une nouvelle période (3 mois)</span>
          </div>
          <input
            type="date"
            className="meeting-inline-input"
            value={periodStart}
            onChange={(e) => setPeriodStart(e.target.value)}
          />
          <button type="submit" className="meeting-inline-submit" disabled={creatingPeriod}>
            {creatingPeriod ? "Enregistrement…" : "Déclarer la période"}
          </button>
        </form>
      )}

      {period && isResponsable && (
        <form onSubmit={addTask} className="meeting-inline-form" style={{ marginBottom: "24px" }}>
          <div className="meeting-inline-form-header">
            <span>Ajouter une tâche</span>
          </div>
          <input
            className="meeting-inline-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nom de la tâche"
            maxLength={160}
          />
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              className="meeting-inline-input"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Catégorie (ex. Communication, Event, Rédactionnel)"
              maxLength={80}
              style={{ flex: 1 }}
            />
            <select
              className="meeting-inline-input"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              style={{ maxWidth: 160 }}
            >
              <option value="tous">Rôle : Tous</option>
              <option value="staff">Rôle : Staff</option>
              <option value="helper">Rôle : Helper</option>
            </select>
          </div>
          <textarea
            className="meeting-inline-textarea"
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
            placeholder="Explication détaillée de la tâche"
            rows={3}
          />
          {isRedactionnel ? (
            <input
              className="meeting-inline-input"
              value={taskDate}
              onChange={(e) => setTaskDate(e.target.value)}
              placeholder="Date libre (ex. à déterminer, Semaine du 12 août...)"
              maxLength={120}
            />
          ) : isEvent ? (
            <div style={{ display: "flex", gap: "10px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
                <label style={{ fontSize: "11px", color: "var(--muted)", fontWeight: 600 }}>Date de début</label>
                <input
                  type="date"
                  className="meeting-inline-input"
                  value={taskDate}
                  onChange={(e) => setTaskDate(e.target.value)}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
                <label style={{ fontSize: "11px", color: "var(--muted)", fontWeight: 600 }}>Date de fin</label>
                <input
                  type="date"
                  className="meeting-inline-input"
                  value={endDate}
                  min={taskDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </div>
            </div>
          ) : (
            <input
              type="date"
              className="meeting-inline-input"
              value={taskDate}
              onChange={(e) => setTaskDate(e.target.value)}
            />
          )}
          <button type="submit" className="meeting-inline-submit" disabled={submitting}>
            <Plus size={16} />
            {submitting ? "Enregistrement…" : "Ajouter la tâche"}
          </button>
        </form>
      )}

      <div style={{ display: "flex", gap: "8px", marginBottom: "14px", flexWrap: "wrap" }}>
        {["tous", "staff", "helper"].map((r) => (
          <button
            key={r}
            type="button"
            className={`btn-ghost ${roleFilter === r ? "btn-locked" : ""}`}
            onClick={() => setRoleFilter(r)}
          >
            {ROLE_LABELS[r]}
          </button>
        ))}
      </div>

      <div className="meetings-list-card dashboard-card">
        {filteredTasks.length === 0 ? (
          <p className="dashboard-empty">Aucune tâche ne correspond à ce filtre.</p>
        ) : (
          <div className="meeting-list" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {filteredTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                isResponsable={isResponsable}
                members={members}
                onRemove={removeTask}
                onToggleSignup={toggleSignup}
                isSignedUp={isSignedUp(task)}
                onRateVolunteer={rateVolunteer}
                onRemoveVolunteer={removeVolunteer}
                onNominate={nominateVolunteer}
              />
            ))}
          </div>
        )}
      </div>

      <div style={{ marginTop: "32px" }}>
        <div className="section-heading">
          <span>ARCHIVES DES PÉRIODES</span>
        </div>
        <div className="meetings-list-card dashboard-card" style={{ padding: 0 }}>
          {archivedPeriods.length === 0 ? (
            <p className="dashboard-empty" style={{ padding: "24px" }}>Aucune période archivée.</p>
          ) : (
            archivedPeriods.map((archivedPeriod) => (
              <ArchivedPeriodRow
                key={archivedPeriod.id}
                period={archivedPeriod}
                isOpen={openArchiveId === archivedPeriod.id}
                onToggle={(id) => setOpenArchiveId((current) => (current === id ? null : id))}
                isResponsable={isResponsable}
                onDelete={removePeriod}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}
