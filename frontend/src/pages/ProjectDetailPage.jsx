import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, Calendar, CheckCircle2, ClipboardList, Download, FileUp,
  Pencil, Plus, Save, Trash2, UserMinus, UserPlus, Users, X,
} from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import TiptapSummaryEditor from "../components/TiptapSummaryEditor";
import AddMemberModal from "../components/AddMemberModal";
import SummaryReader from "../components/SummaryReader";

const TASK_STATUS_LABELS = { a_faire: "À faire", en_cours: "En cours", rendu: "Rendue", valide: "Validée" };

function MemberAvatar({ member, size = 26 }) {
  const label = member?.display_name || member?.username || "";
  return (
    <span className="absence-avatar" style={{ width: size, height: size }} title={label}>
      {member?.avatar_url ? <img src={member.avatar_url} alt="" /> : <Users size={Math.round(size * 0.55)} />}
    </span>
  );
}

function TaskCard({ task, currentHelperId, isResponsable, onSubmit, onValidate, onDelete }) {
  const [note, setNote] = useState(task.submission_note || "");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const isAssignee = task.assignee.id === currentHelperId;

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit(task.id, note, file);
      setFile(null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="meeting-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <MemberAvatar member={task.assignee} size={22} />
            <strong>{task.title}</strong>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            <Calendar size={14} /> <span>{task.due_date}</span>
          </div>
          {task.description && <p style={{ fontSize: 13, color: "var(--muted)", margin: "8px 0 0" }}>{task.description}</p>}
        </div>
        <span className={`status-badge ${task.status === "valide" ? "status-done" : "status-pending"}`}>
          {TASK_STATUS_LABELS[task.status]}
        </span>
      </div>

      {task.status === "rendu" && (
        <div style={{ fontSize: 13, color: "var(--muted)", background: "#f7faf7", padding: 10, borderRadius: 8 }}>
          {task.submission_note && <SummaryReader content={task.submission_note} />}
          {task.submission_file && (
            <a
              href={`/api/animateur/tasks/${task.id}/submission/download`}
              onClick={(e) => e.stopPropagation()}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 6 }}
            >
              <FileUp size={14} /> {task.submission_file.original_filename}
            </a>
          )}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {isAssignee && (task.status === "a_faire" || task.status === "en_cours") && (
          <>
            <TiptapSummaryEditor
              value={note}
              onChange={setNote}
              placeholder="Décrire le rendu, tapez / pour les commandes"
            />
            <input type="file" onChange={(e) => setFile(e.target.files[0])} />
            <button
              type="button"
              className="calm-primary-button is-secondary"
              onClick={handleSubmit}
              disabled={submitting}
              style={{ alignSelf: "flex-start" }}
            >
              <FileUp size={15} /> {submitting ? "Envoi…" : "Rendre la tâche"}
            </button>
          </>
        )}
        {isResponsable && task.status === "rendu" && (
          <button type="button" className="calm-primary-button" onClick={() => onValidate(task.id)}>
            <CheckCircle2 size={15} /> Valider
          </button>
        )}
        {isResponsable && (
          <button type="button" className="icon-btn-danger" onClick={() => onDelete(task.id)} aria-label="Supprimer">
            <Trash2 size={15} />
          </button>
        )}
      </div>
    </div>
  );
}

function ValidatedTaskRow({ task }) {
  return (
    <div className="meeting-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <MemberAvatar member={task.assignee} size={22} />
            <strong>{task.title}</strong>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            <Calendar size={14} />
            <span>Rendu par {task.assignee.display_name || task.assignee.username} · échéance {task.due_date}</span>
          </div>
        </div>
        <span className="status-badge status-done">Validée</span>
      </div>

      {task.submission_note && (
        <div style={{ fontSize: 13, color: "var(--muted)", background: "#f7faf7", padding: 10, borderRadius: 8 }}>
          <SummaryReader content={task.submission_note} />
        </div>
      )}

      {task.submission_file && (
        <a
          href={`/api/animateur/tasks/${task.id}/submission/download`}
          onClick={(e) => e.stopPropagation()}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}
        >
          <FileUp size={14} /> {task.submission_file.original_filename}
        </a>
      )}
    </div>
  );
}

export default function ProjectDetailPage({ helper, isResponsableGlobal }) {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [resources, setResources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isEditingContent, setIsEditingContent] = useState(false);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [showAddMember, setShowAddMember] = useState(false);

  const [taskTitle, setTaskTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [taskAssigneeId, setTaskAssigneeId] = useState("");
  const [taskDueDate, setTaskDueDate] = useState(new Date().toISOString().slice(0, 10));
  const [creatingTask, setCreatingTask] = useState(false);

  const [resourceTitle, setResourceTitle] = useState("");
  const [resourceFile, setResourceFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [downloadingId, setDownloadingId] = useState(null);

  const isResponsable = isResponsableGlobal || project?.created_by?.id === helper?.id;

  const activeTasks = tasks.filter((task) => task.status !== "valide");
  const validatedTasks = tasks.filter((task) => task.status === "valide");

  const load = async () => {
    setLoading(true);
    try {
      const [projectResponse, tasksResponse, resourcesResponse] = await Promise.all([
        api.get(`/animateur/projects/${projectId}`),
        api.get(`/animateur/projects/${projectId}/tasks`),
        api.get(`/animateur/projects/${projectId}/resources`),
      ]);
      setProject(projectResponse.data);
      setContent(projectResponse.data.content_markdown || "");
      setTasks(tasksResponse.data);
      setResources(resourcesResponse.data);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const saveContent = async () => {
    setSaving(true);
    try {
      const response = await api.put(`/animateur/projects/${projectId}`, {
        title: project.title,
        description: project.description,
        content_markdown: content,
        end_date: project.end_date,
      });
      setProject(response.data);
      setIsEditingContent(false);
      toast.success("Projet mis à jour.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };
const downloadTaskFile = async (taskId, submissionFile) => {
  setDownloadingTaskFileId(taskId);
  try {
    const response = await api.get(`/animateur/tasks/${taskId}/submission/download`, {
      responseType: "blob",
    });
    const url = window.URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = submissionFile.original_filename || "fichier";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    toast.error(getErrorMessage(error));
  } finally {
    setDownloadingTaskFileId(null);
  }
};
  const createTask = async (event) => {
    event.preventDefault();
    if (!taskTitle.trim() || !taskAssigneeId) {
      toast.error("Titre et membre assigné requis.");
      return;
    }
    setCreatingTask(true);
    try {
      const response = await api.post(`/animateur/projects/${projectId}/tasks`, {
        project_id: projectId,
        assignee_id: taskAssigneeId,
        title: taskTitle,
        description: taskDescription,
        due_date: taskDueDate,
      });
      setTasks((current) => [...current, response.data]);
      setTaskTitle("");
      setTaskDescription("");
      setTaskAssigneeId("");
      toast.success("Tâche ajoutée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreatingTask(false);
    }
  };

  const submitTask = async (taskId, note, file) => {
    try {
      const formData = new FormData();
      formData.append("submission_content", note);
      if (file) formData.append("file", file);
      const response = await api.put(`/animateur/tasks/${taskId}/submit`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setTasks((current) => current.map((task) => (task.id === taskId ? response.data : task)));
      toast.success("Tâche rendue.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const validateTask = async (taskId) => {
    try {
      const response = await api.put(`/animateur/tasks/${taskId}/validate`);
      setTasks((current) => current.map((task) => (task.id === taskId ? response.data : task)));
      toast.success("Tâche validée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const deleteTask = async (taskId) => {
    try {
      await api.delete(`/animateur/tasks/${taskId}`);
      setTasks((current) => current.filter((task) => task.id !== taskId));
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const uploadResource = async (event) => {
    event.preventDefault();
    if (!resourceFile) {
      toast.error("Choisissez un fichier.");
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("title", resourceTitle || resourceFile.name);
      formData.append("file", resourceFile);
      const response = await api.post(`/animateur/projects/${projectId}/resources`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResources((current) => [response.data, ...current]);
      setResourceTitle("");
      setResourceFile(null);
      toast.success("Ressource ajoutée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  };

  const downloadResource = async (resource) => {
    setDownloadingId(resource.id);
    try {
      const response = await api.get(`/animateur/resources/${resource.id}/download`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = resource.original_filename || resource.title;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setDownloadingId(null);
    }
  };

  const removeMember = async (memberId) => {
    try {
      const response = await api.delete(`/animateur/projects/${projectId}/members/${memberId}`);
      setProject(response.data);
      toast.success("Membre retiré du projet.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  if (loading) {
    return (
      <section className="page-content dashboard-page">
        <p className="dashboard-loading">Chargement…</p>
      </section>
    );
  }
  if (!project) return null;

  return (
    <section className="page-content dashboard-page" data-testid="project-detail-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">ESPACE ANIMATEUR</p>
          <h1>{project.title}</h1>
          <p style={{ color: "var(--muted)", marginTop: 6 }}>{project.description}</p>
        </div>
        <div className="dashboard-actions">
          <button type="button" className="btn-ghost" onClick={() => navigate("/animateur/projects")}>
            <ArrowLeft size={17} /> Retour
          </button>
        </div>
      </header>

      <div className="workspace-grid" style={{ padding: 0 }}>
        <div className="workspace-column">
          <div className="section-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>CONTENU DU PROJET</span>
            {!isEditingContent ? (
              <button type="button" className="btn-ghost" onClick={() => setIsEditingContent(true)}>
                <Pencil size={15} /> Éditer
              </button>
            ) : (
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => {
                    setContent(project.content_markdown || "");
                    setIsEditingContent(false);
                  }}
                >
                  <X size={15} /> Annuler
                </button>
                <button type="button" className="btn-primary" onClick={saveContent} disabled={saving}>
                  <Save size={15} /> {saving ? "Enregistrement…" : "Enregistrer"}
                </button>
              </div>
            )}
          </div>
          <div style={{ padding: 20 }}>
            {isEditingContent ? (
              <TiptapSummaryEditor
                value={content}
                onChange={setContent}
                placeholder="Décrire le projet, tapez / pour les commandes"
                autoFocus
              />
            ) : project.content_markdown ? (
              <SummaryReader content={project.content_markdown} />
            ) : (
              <p className="resources-empty">Aucun contenu pour l'instant.</p>
            )}
          </div>

          <div className="section-heading">
            <span>TÂCHES INTERNES</span>
          </div>
          <div style={{ padding: "0 20px 20px" }}>
            {isResponsable && (
              <form onSubmit={createTask} className="meeting-inline-form" style={{ marginBottom: 20 }}>
                <div className="meeting-inline-form-header">
                  <span>Assigner une tâche</span>
                </div>
                <input
                  className="meeting-inline-input"
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  placeholder="Titre de la tâche"
                  maxLength={160}
                />
                <textarea
                  className="meeting-inline-textarea"
                  value={taskDescription}
                  onChange={(e) => setTaskDescription(e.target.value)}
                  placeholder="Description (optionnel)"
                  rows={2}
                />
                <select
                  className="meeting-inline-input"
                  value={taskAssigneeId}
                  onChange={(e) => setTaskAssigneeId(e.target.value)}
                >
                  <option value="">Choisir un membre</option>
                  {project.members.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.display_name || member.username}
                    </option>
                  ))}
                </select>
                <input
                  type="date"
                  className="meeting-inline-input"
                  value={taskDueDate}
                  onChange={(e) => setTaskDueDate(e.target.value)}
                />
                <button type="submit" className="meeting-inline-submit" disabled={creatingTask}>
                  <Plus size={16} /> {creatingTask ? "Ajout…" : "Ajouter la tâche"}
                </button>
              </form>
            )}
            {activeTasks.length === 0 ? (
              <p className="resources-empty">Aucune tâche en cours pour ce projet.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {activeTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    currentHelperId={helper?.id}
                    isResponsable={isResponsable}
                    onSubmit={submitTask}
                    onValidate={validateTask}
                    onDelete={deleteTask}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="intelligence-panel">
          <div className="section-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>MEMBRES DU PROJET</span>
            {isResponsable && (
              <button type="button" className="btn-ghost" onClick={() => setShowAddMember(true)}>
                <UserPlus size={15} /> Ajouter
              </button>
            )}
          </div>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            {project.members.map((member) => (
              <div key={member.id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <MemberAvatar member={member} size={30} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong style={{ display: "block", fontSize: 13 }}>{member.display_name || member.username}</strong>
                  <small style={{ color: "var(--muted)" }}>
                    {member.role === "responsable" ? "Responsable" : "Membre"}
                  </small>
                </div>
                {isResponsable && member.id !== project.created_by.id && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => removeMember(member.id)}
                    aria-label="Retirer"
                  >
                    <UserMinus size={15} />
                  </button>
                )}
              </div>
            ))}
          </div>

          <div className="section-heading">
            <span>RESSOURCES ANNEXES</span>
          </div>
          <div style={{ padding: 16 }}>
            <form onSubmit={uploadResource} style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
              <input
                className="meeting-inline-input"
                value={resourceTitle}
                onChange={(e) => setResourceTitle(e.target.value)}
                placeholder="Titre du document"
              />
              <input type="file" onChange={(e) => setResourceFile(e.target.files[0])} />
              <button type="submit" className="calm-primary-button is-secondary" disabled={uploading}>
                <FileUp size={15} /> {uploading ? "Envoi…" : "Déposer la ressource"}
              </button>
            </form>
            {resources.length === 0 ? (
              <p className="resources-empty">Aucune ressource déposée.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {resources.map((resource) => (
                  <div
                    key={resource.id}
                    onClick={() => downloadResource(resource)}
                    role="button"
                    tabIndex={0}
                    className="absence-meeting-row"
                    style={{
                      display: "flex", alignItems: "center", gap: 10, padding: 10,
                      borderRadius: 8, background: "#f7faf7", cursor: "pointer",
                      opacity: downloadingId === resource.id ? 0.6 : 1,
                    }}
                  >
                    <ClipboardList size={16} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <strong style={{ display: "block", fontSize: 13 }}>{resource.title}</strong>
                      <small style={{ color: "var(--muted)" }}>{resource.original_filename}</small>
                    </div>
                    <Download size={15} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="dashboard-card" style={{ marginTop: 24, padding: 0 }}>
        <div className="section-heading">
          <span>TÂCHES VALIDÉES</span>
        </div>
        <div style={{ padding: "0 20px 20px" }}>
          {validatedTasks.length === 0 ? (
            <p className="resources-empty">Aucune tâche validée pour l'instant.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {validatedTasks.map((task) => (
                <ValidatedTaskRow key={task.id} task={task} />
              ))}
            </div>
          )}
        </div>
      </div>

      {showAddMember && (
        <AddMemberModal
          projectId={projectId}
          existingIds={project.members.map((m) => m.id)}
          onAdded={(updatedProject) => setProject(updatedProject)}
          onClose={() => setShowAddMember(false)}
        />
      )}
    </section>
  );
}
