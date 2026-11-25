import { SuccessCheck } from "./motion/Motion";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Circle } from "lucide-react";
import { Link } from "react-router-dom";
import { api, getErrorMessage } from "../api/client";

function formatDate(value) {
  if (!value) return "Date à préciser";

  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }

  return new Date(`${value}T12:00:00`).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
  });
}

export default function QuarterlyDashboardModule({ helper }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("pending");

  const queryKey = ["dashboard", "quarterly-tasks", helper?.id];

  const tasksQuery = useQuery({
    queryKey,
    enabled: Boolean(helper?.id),
    queryFn: async ({ signal }) => {
      const periodResponse = await api.get("/staff/tasks/period", {
        signal,
      });

      const period = periodResponse.data;

      if (!period) {
        return { period: null, tasks: [] };
      }

      const tasksResponse = await api.get("/staff/tasks", {
        params: { period_id: period.id },
        signal,
      });

      if (!Array.isArray(tasksResponse.data)) {
        throw new Error("Format des tâches inattendu.");
      }

      const tasks = tasksResponse.data
        .filter((task) =>
          (task.volunteers || []).some(
            (volunteer) =>
              String(volunteer.id) === String(helper.id)
          )
        )
        .map((task) => {
          const participation = task.volunteers.find(
            (volunteer) =>
              String(volunteer.id) === String(helper.id)
          );

          return {
            ...task,
            completed: participation?.completed === true,
          };
        });

      return { period, tasks };
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const completionMutation = useMutation({
    mutationFn: async ({ taskId, completed }) => {
      await api.patch(`/staff/tasks/${taskId}/completion`, {
        completed,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey,
        exact: true,
      });
    },
  });

  const tasks = tasksQuery.data?.tasks || [];

  const visibleTasks = tasks.filter((task) => {
    if (filter === "pending") return !task.completed;
    if (filter === "completed") return task.completed;
    return true;
  });

  const filters = [
    { id: "pending", label: "À faire" },
    { id: "completed", label: "Terminées" },
    { id: "all", label: "Toutes" },
  ];

  return (
    <section className="nd-work-module nd-work-module--quarterly">
      <header className="nd-work-header">
        <div>
          <p className="nd-eyebrow">MES ENGAGEMENTS</p>
          <h2>Mes tâches trimestrielles</h2>
          <p className="nd-description">
            Les tâches de la période en cours auxquelles vous êtes inscrit.
          </p>
        </div>

        <Link to="/staff/taches" className="nd-work-link">
          Liste complète
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </header>

      <div className="nd-work-panel">
        <div className="nd-work-toolbar">
          <div className="nd-work-filters" aria-label="Filtrer les tâches">
            {filters.map((item) => (
              <button
                key={item.id}
                type="button"
                className={filter === item.id ? "is-selected" : ""}
                aria-pressed={filter === item.id}
                onClick={() => setFilter(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tasksQuery.data?.period && (
            <span className="nd-work-period">
              {formatDate(tasksQuery.data.period.start_date)}
              {" → "}
              {formatDate(tasksQuery.data.period.end_date)}
            </span>
          )}
        </div>

        {tasksQuery.isPending ? (
          <p className="nd-work-message" role="status">
            Chargement de vos tâches…
          </p>
        ) : tasksQuery.isError ? (
          <div className="nd-work-message" role="alert">
            <p>Impossible de charger vos tâches.</p>
            <button type="button" onClick={() => tasksQuery.refetch()}>
              Réessayer
            </button>
          </div>
        ) : !tasksQuery.data?.period ? (
          <p className="nd-work-message">
            Aucune période trimestrielle n’est actuellement déclarée.
          </p>
        ) : visibleTasks.length === 0 ? (
          <p className="nd-work-message">
            {tasks.length === 0
              ? "Vous n’êtes inscrit à aucune tâche pour cette période."
              : "Aucune tâche ne correspond à ce filtre."}
          </p>
        ) : (
          <div className="nd-work-list">
            {visibleTasks.map((task) => (
              <div className="nd-work-row" key={task.id} data-iris-reveal="message">
                <span
                  className={`nd-work-task-icon ${
                    task.completed ? "is-completed" : ""
                  }`}
                >
                  {task.completed ? (
                    <SuccessCheck size={21} />
                  ) : (
                    <Circle size={21} aria-hidden="true" />
                  )}
                </span>

                <div className="nd-work-copy">
                  <strong>{task.name}</strong>
                  <small>
                    {task.category}
                    {" · "}
                    {formatDate(task.task_date)}
                    {task.end_date && ` → ${formatDate(task.end_date)}`}
                  </small>

                  {task.explanation && (
                    <p>{task.explanation}</p>
                  )}
                </div>

                <button
                  type="button"
                  className={`nd-work-completion ${
                    task.completed ? "is-completed" : ""
                  }`}
                  disabled={completionMutation.isPending}
                  onClick={() =>
                    completionMutation.mutate({
                      taskId: task.id,
                      completed: !task.completed,
                    })
                  }
                >
                  {completionMutation.isPending &&
                  completionMutation.variables?.taskId === task.id
                    ? "Enregistrement…"
                    : task.completed
                      ? "Remettre à faire"
                      : "Marquer terminée"}
                </button>
              </div>
            ))}
          </div>
        )}

        {completionMutation.isError && (
          <p className="nd-work-error" role="alert">
            {getErrorMessage(completionMutation.error)}
          </p>
        )}
      </div>
    </section>
  );
}
