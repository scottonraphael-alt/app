import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Calendar, FolderKanban, Plus, Users, X } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
const STATUS_LABELS = { en_cours: "En cours", termine: "Terminé", archive: "Archivé" };
const STATUS_CLASSES = { en_cours: "status-pending", termine: "status-done", archive: "status-archived" };

function MemberStack({ members }) {
  const visible = members.slice(0, 4);
  const extra = members.length - visible.length;
  return (
    <div className="project-member-stack">
      {visible.map((member) => (
        <span key={member.id} className="project-member-avatar" title={member.display_name || member.username}>
          {member.avatar_url ? <img src={member.avatar_url} alt="" /> : <Users size={12} />}
        </span>
      ))}
      {extra > 0 && <span className="project-member-avatar project-member-extra">+{extra}</span>}
    </div>
  );
}

function ProjectCard({
  project,
  helper,
  isResponsableGlobal,
  onJoin,
  joiningId,
  onArchive,
  archivingId,
  onDelete,
}) {
  const isMember = project.members.some((member) => member.id === helper?.id);
  const isJoining = joiningId === project.id;
  const isArchiving = archivingId === project.id;
  const isArchived = project.status === "archive";
  const canArchive = isResponsableGlobal || project.created_by?.id === helper?.id;

  const handleJoin = (event) => {
    event.preventDefault();
    event.stopPropagation();
    onJoin(project.id);
  };

  const handleArchive = (event) => {
    event.preventDefault();
    event.stopPropagation();
    onArchive(project, !isArchived);
  };

  const handleDelete = (event) => {
    event.preventDefault();
    event.stopPropagation();
    onDelete(project);
  };

  return (
    <Link
      to={`/animateur/projects/${project.id}`}
      className={`resource-card project-card ${isArchived ? "project-card-archived" : ""}`}
      style={{ textDecoration: "none" }}
    >
      <div className="project-card-top">
        <span className="resource-type">
          <FolderKanban size={18} />
        </span>
        <span className={`status-badge ${STATUS_CLASSES[project.status]}`}>
          {STATUS_LABELS[project.status]}
        </span>
      </div>

      <h2 className="project-card-title">{project.title}</h2>
      <p className="project-card-description">
        {project.description || "Aucune description."}
      </p>

      <div className="project-card-footer">
        <MemberStack members={project.members} />
        <span className="project-card-dates">
          <Calendar size={13} /> {project.start_date} → {project.end_date || "…"}
        </span>
      </div>

      <div className="project-card-actions">
        {!isMember && !isArchived && (
          <button
            type="button"
            className="calm-primary-button is-secondary"
            onClick={handleJoin}
            disabled={isJoining}
          >
            {isJoining ? "Inscription…" : "S'inscrire"}
          </button>
        )}

        {canArchive && (
          <button
            type="button"
            className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
            onClick={handleDelete}
          >
            Supprimer
          </button>
        )}

        {canArchive && (
          <button
            type="button"
            className="btn-ghost project-archive-btn"
            onClick={handleArchive}
            disabled={isArchiving}
          >
            {isArchived ? <ArchiveRestore size={15} /> : <Archive size={15} />}
            {isArchiving ? "…" : isArchived ? "Désarchiver" : "Archiver"}
          </button>
        )}
      </div>
    </Link>
  );
}
export default function ProjectsListPage({ helper, isResponsableGlobal, isResponsable }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [joiningId, setJoiningId] = useState(null);
  const [archivingId, setArchivingId] = useState(null);
  const [viewMode, setViewMode] = useState("actifs");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get("/animateur/projects")
      .then((response) => setProjects(response.data))
      .catch((error) => toast.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const resetForm = () => {
    setTitle("");
    setDescription("");
    setStartDate(new Date().toISOString().slice(0, 10));
    setEndDate("");
    setShowForm(false);
  };

  const createProject = async (event) => {
    event.preventDefault();
    if (!title.trim()) {
      toast.error("Ajoutez au moins un titre.");
      return;
    }
    setCreating(true);
    try {
      const response = await api.post("/animateur/projects", {
        title, description, start_date: startDate, end_date: endDate || null,
      });
      setProjects((current) => [response.data, ...current]);
      toast.success("Projet créé.");
      resetForm();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const joinProject = async (projectId) => {
    if (!helper?.id) {
      toast.error("Impossible d'identifier votre profil.");
      return;
    }
    setJoiningId(projectId);
    try {
      const response = await api.post(`/animateur/projects/${projectId}/members`, { member_id: helper.id });
      setProjects((current) => current.map((project) => (project.id === projectId ? response.data : project)));
      toast.success("Vous avez rejoint le projet.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setJoiningId(null);
    }
  };

  const archiveProject = async (project, archive) => {
    setArchivingId(project.id);
    try {
      const response = await api.put(`/animateur/projects/${project.id}`, {
        title: project.title,
        description: project.description,
        content_markdown: project.content_markdown,
        end_date: project.end_date,
        status: archive ? "archive" : "en_cours",
      });
      setProjects((current) => current.map((p) => (p.id === project.id ? response.data : p)));
      toast.success(archive ? "Projet archivé." : "Projet désarchivé.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setArchivingId(null);
    }
  };
const deleteProject = async (project) => {
  const confirmed = window.confirm(`Supprimer définitivement "${project.title}" ?`);
  if (!confirmed) return;

  try {
    await api.delete(`/animateur/projects/${project.id}`, { withCredentials: true });
    setProjects((current) => current.filter((item) => item.id !== project.id));
    toast.success("Projet supprimé.");
  } catch (error) {
    toast.error(getErrorMessage(error));
  }
};
const filteredProjects = projects.filter((project) =>
  viewMode === "archives" ? project.status === "archive" : project.status !== "archive"
);
  return (
    <section className="page-content resources-page" data-testid="projects-list-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">ESPACE ANIMATEUR</p>
          <h1>Projets d'Events</h1>
        </div>
        <div className="dashboard-actions">
          {!showForm ? (
            <button type="button" className="calm-primary-button" onClick={() => setShowForm(true)} data-testid="new-project-button">
              <Plus size={17} /> Nouveau projet
            </button>
          ) : (
            <button type="button" className="calm-primary-button is-cancel" onClick={resetForm}>
              <X size={17} /> Annuler
            </button>
          )}
        </div>
      </header>

      <div className="project-view-tabs">
        <button
          type="button"
          className={`project-view-tab ${viewMode === "actifs" ? "is-active" : ""}`}
          onClick={() => setViewMode("actifs")}
        >
          Actifs
        </button>
        <button
          type="button"
          className={`project-view-tab ${viewMode === "archives" ? "is-active" : ""}`}
          onClick={() => setViewMode("archives")}
        >
          <Archive size={14} /> Archivés
        </button>
      </div>

      {showForm && (
        <form onSubmit={createProject} className="meeting-inline-form" style={{ marginBottom: 28 }}>
          <div className="meeting-inline-form-header"><span>Nouveau projet</span></div>
          <input
            className="meeting-inline-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Titre du projet"
            maxLength={160}
          />
          <textarea
            className="meeting-inline-textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description du projet"
            rows={3}
          />
          <div className="case-form-grid">
            <div>
              <label>Date de début</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            <div>
              <label>Date de fin (optionnel)</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
          </div>
          <button type="submit" className="meeting-inline-submit" disabled={creating}>
            <Plus size={16} /> {creating ? "Création…" : "Créer le projet"}
          </button>
        </form>
      )}

      {loading ? (
        <p className="resources-empty">Chargement…</p>
      ) : filteredProjects.length === 0 ? (
        <p className="resources-empty">
          {viewMode === "archives" ? "Aucun projet archivé." : "Aucun projet pour l'instant."}
        </p>
      ) : (
        <div className="resource-grid">
          {filteredProjects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              helper={helper}
              isResponsableGlobal={isResponsableGlobal}
              onJoin={joinProject}
              joiningId={joiningId}
              onArchive={archiveProject}
              archivingId={archivingId}
              onDelete={deleteProject}
            />
          ))}
        </div>
      )}
    </section>
  );
}
