import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  ChevronDown,
  FolderKanban,
} from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";

function localDateKey() {
  const now = new Date();

  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
}

function dateKey(value) {
  const key = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null;
}

function parseDate(value) {
  const key = dateKey(value);
  if (!key) return null;

  const date = new Date(`${key}T12:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function shortDate(value) {
  const date = parseDate(value);

  return date
    ? date.toLocaleDateString("fr-FR", {
        day: "numeric",
        month: "short",
      })
    : "Sans échéance";
}

function UpcomingProject({ project }) {
  const date = parseDate(project.start_date);

  return (
    <Link
      to={`/animateur/projects/${project.id}`}
      className="nd-anim-upcoming-row"
    >
      <span className="nd-anim-date" aria-hidden="true">
        <strong>{date?.getDate()}</strong>
        <small>
          {date?.toLocaleDateString("fr-FR", {
            month: "short",
          })}
        </small>
      </span>

      <span className="nd-anim-upcoming-copy">
        <strong>{project.title}</strong>

        <small>
          Début le{" "}
          {date?.toLocaleDateString("fr-FR", {
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        </small>
      </span>

      <ArrowRight size={17} aria-hidden="true" />
    </Link>
  );
}

function CompactProject({ project, helperId }) {
  const tasksQuery = useQuery({
    queryKey: ["dashboard", "project-tasks", project.id, helperId],
    queryFn: async ({ signal }) => {
      const response = await api.get(
        `/animateur/projects/${project.id}/tasks`,
        { signal }
      );

      if (!Array.isArray(response.data)) {
        throw new Error("Format des tâches inattendu.");
      }

      return response.data
        .filter(
          (task) =>
            String(task.assignee?.id) === String(helperId) &&
            ["a_faire", "en_cours"].includes(task.status)
        )
        .sort((a, b) =>
          (a.due_date || "9999").localeCompare(b.due_date || "9999")
        );
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const tasks = tasksQuery.data || [];

  const countLabel = tasksQuery.isPending
    ? "Chargement…"
    : tasksQuery.isError
      ? "Tâches indisponibles"
      : `${tasks.length} tâche${tasks.length > 1 ? "s" : ""} à faire`;

  return (
    <details className="nd-anim-project">
      <summary className="nd-anim-project-summary">
        <span className="nd-anim-project-icon">
          <FolderKanban size={20} aria-hidden="true" />
        </span>

        <span className="nd-anim-project-copy">
          <strong>{project.title}</strong>
          <small>
            {project.end_date
              ? `Fin prévue : ${shortDate(project.end_date)}`
              : "Projet en cours"}
          </small>
        </span>

        <span className="nd-anim-task-count">{countLabel}</span>

        <ChevronDown
          className="nd-anim-chevron"
          size={17}
          aria-hidden="true"
        />
      </summary>

      <div className="nd-anim-project-body">
        {tasksQuery.isPending ? (
          <p className="nd-anim-message" role="status">
            Chargement de vos tâches…
          </p>
        ) : tasksQuery.isError ? (
          <div className="nd-anim-message" role="alert">
            <p>Impossible de charger vos tâches.</p>
            <button type="button" onClick={() => tasksQuery.refetch()}>
              Réessayer
            </button>
          </div>
        ) : tasks.length === 0 ? (
          <p className="nd-anim-message">
            Aucune tâche à réaliser ne vous est attribuée.
          </p>
        ) : (
          <div className="nd-anim-task-list">
            {tasks.map((task) => (
              <Link
                key={task.id}
                to={`/animateur/projects/${project.id}?task=${encodeURIComponent(task.id)}`}
                className="nd-anim-task-row"
              >
                <span className="nd-anim-task-dot" aria-hidden="true" />

                <span className="nd-anim-task-title">
                  {task.title}
                </span>

                <small>{shortDate(task.due_date)}</small>

                <ArrowRight size={15} aria-hidden="true" />
              </Link>
            ))}
          </div>
        )}

        <Link
          to={`/animateur/projects/${project.id}`}
          className="nd-anim-project-footer"
        >
          Ouvrir le projet et rendre mon travail
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    </details>
  );
}

export default function AnimateurDashboardModule({ helper }) {
  const projectsQuery = useQuery({
    queryKey: ["dashboard", "animateur-projects", helper?.id],
    enabled: Boolean(helper?.id),
    queryFn: async ({ signal }) => {
      const response = await api.get("/animateur/projects", {
        signal,
      });

      if (!Array.isArray(response.data)) {
        throw new Error("Format des projets inattendu.");
      }

      return response.data;
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const projects = projectsQuery.data || [];
  const today = localDateKey();

  const myProjects = projects.filter(
    (project) =>
      project.status === "en_cours" &&
      (!dateKey(project.start_date) ||
        dateKey(project.start_date) <= today) &&
      (project.members || []).some(
        (member) => String(member.id) === String(helper?.id)
      )
  );

  const upcomingProjects = projects
    .filter((project) => {
      const start = dateKey(project.start_date);

      return (
        project.status === "en_cours" &&
        start &&
        start > today
      );
    })
    .sort((a, b) =>
      dateKey(a.start_date).localeCompare(dateKey(b.start_date))
    );

  return (
    <section
      className="nd-work-module nd-anim-module"
      aria-labelledby="nd-anim-title"
    >
      <header className="nd-work-header">
        <div>
          <p className="nd-eyebrow">CRÉER ENSEMBLE</p>
          <h2 id="nd-anim-title">Mon espace animateur</h2>
          <p className="nd-description">
            Vos projets, vos tâches et les prochaines animations.
          </p>
        </div>

        <Link to="/animateur/projects" className="nd-work-link">
          Tous les projets
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </header>

      {projectsQuery.isPending ? (
        <div className="nd-work-panel nd-work-message" role="status">
          Chargement des projets…
        </div>
      ) : projectsQuery.isError ? (
        <div className="nd-work-panel nd-work-message" role="alert">
          <p>Impossible de charger les projets.</p>
          <button type="button" onClick={() => projectsQuery.refetch()}>
            Réessayer
          </button>
        </div>
      ) : (
        <div className="nd-anim-layout">
          <section
            className="nd-anim-panel"
            aria-labelledby="nd-anim-current-title"
          >
            <header className="nd-anim-panel-heading">
              <span className="nd-anim-heading-icon">
                <FolderKanban size={20} aria-hidden="true" />
              </span>

              <div>
                <h3 id="nd-anim-current-title">Mes projets en cours</h3>
                <p>Dépliez un projet pour retrouver vos tâches.</p>
              </div>
            </header>

            <div className="nd-anim-scroll">
              {myProjects.length === 0 ? (
                <p className="nd-anim-message">
                  Aucun projet démarré auquel vous participez.
                </p>
              ) : (
                myProjects.map((project) => (
                  <CompactProject
                    key={project.id}
                    project={project}
                    helperId={helper.id}
                  />
                ))
              )}
            </div>
          </section>

          <section
            className="nd-anim-panel nd-anim-calendar"
            aria-labelledby="nd-anim-upcoming-title"
          >
            <header className="nd-anim-panel-heading">
              <span className="nd-anim-heading-icon">
                <CalendarDays size={20} aria-hidden="true" />
              </span>

              <div>
                <h3 id="nd-anim-upcoming-title">À venir</h3>
                <p>Les prochains projets prévus au calendrier.</p>
              </div>
            </header>

            <div className="nd-anim-scroll">
              {upcomingProjects.length === 0 ? (
                <p className="nd-anim-message">
                  Aucun projet à venir pour le moment.
                </p>
              ) : (
                upcomingProjects.map((project) => (
                  <UpcomingProject
                    key={project.id}
                    project={project}
                  />
                ))
              )}
            </div>

            <Link
              to="/animateur/calendrier"
              className="nd-anim-calendar-footer"
            >
              Ouvrir le calendrier complet
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
          </section>
        </div>
      )}
    </section>
  );
}
