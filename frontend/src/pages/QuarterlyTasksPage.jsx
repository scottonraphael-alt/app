import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Archive,
  Calendar,
  ChevronDown,
  Plus,
  Search,
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

const ROLE_STYLES = {
  tous: "bg-slate-100 text-slate-600 border-slate-200",
  staff: "bg-violet-100 text-violet-700 border-violet-200",
  helper: "bg-sky-100 text-sky-700 border-sky-200",
};

/* Statut de la tâche -> couleur de bordure gauche de la carte
   (même logique que les fiches de casier : couleur = gravité/état) */
const STATUS_META = {
  ouverte: { label: "Ouverte", border: "border-l-slate-300", pill: "bg-slate-100 text-slate-600" },
  en_cours: { label: "En cours", border: "border-l-amber-400", pill: "bg-amber-100 text-amber-700" },
  complete: { label: "Complète", border: "border-l-emerald-400", pill: "bg-emerald-100 text-emerald-700" },
  archivee: { label: "Archivée", border: "border-l-slate-200", pill: "bg-slate-100 text-slate-400" },
};

function computeStatus(task) {
  if (task.archived) return "archivee";
  if (task.max_volunteers && task.volunteers.length >= task.max_volunteers) return "complete";
  if (task.volunteers.length > 0) return "en_cours";
  return "ouverte";
}

/* ---------------------------------------------------------------------- */
/* Avatar rond (même composant que le casier)                             */
/* ---------------------------------------------------------------------- */

function MemberAvatar({ member, size = 30 }) {
  const [imageError, setImageError] = useState(false);
  const label = member?.display_name || member?.username || "?";
  const avatarUrl = member?.avatar_url;

  if (!avatarUrl || imageError) {
    return (
      <span
        className="inline-flex items-center justify-center rounded-full bg-slate-200 text-slate-600 font-medium shrink-0"
        style={{ width: size, height: size, fontSize: size * 0.42 }}
        title={label}
      >
        {label.charAt(0).toUpperCase()}
      </span>
    );
  }

  return (
    <img
      src={avatarUrl}
      alt={label}
      width={size}
      height={size}
      onError={() => setImageError(true)}
      className="rounded-full object-cover shrink-0 border border-white shadow-sm"
      style={{ width: size, height: size }}
    />
  );
}

/* ---------------------------------------------------------------------- */
/* Sélecteur de nomination                                                */
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
    <div className="flex items-center gap-2">
      <div className="relative">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="appearance-none rounded-full border border-slate-200 bg-white pl-3 pr-8 py-1.5 text-sm text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-200"
        >
          <option value="">Nommer quelqu'un…</option>
          {available.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name || m.username}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
      </div>
      <button
        type="button"
        onClick={handleNominate}
        disabled={!selected}
        className="inline-flex items-center gap-1 rounded-full bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
      >
        <UserPlus className="h-3.5 w-3.5" />
        Nommer
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Carte de tâche — style "fiche de casier"                               */
/* ---------------------------------------------------------------------- */

function TaskCard({ task, members, onVolunteer, onWithdraw, onNominate, onArchive, onDelete, currentUserId }) {
  const [expanded, setExpanded] = useState(false);
  const status = computeStatus(task);
  const meta = STATUS_META[status];
  const isVolunteer = task.volunteers.some((v) => v.id === currentUserId);

  return (
    <div
      className={`bg-white rounded-2xl border border-slate-100 border-l-4 ${meta.border} shadow-sm hover:shadow-md transition-shadow p-4`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-slate-800 truncate">{task.title}</h3>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${meta.pill}`}>
              {meta.label}
            </span>
            {task.role && (
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded-full border ${ROLE_STYLES[task.role] || ROLE_STYLES.tous}`}
              >
                {ROLE_LABELS[task.role] || task.role}
              </span>
            )}
            {task.priority && (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600">
                <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
                Prioritaire
              </span>
            )}
          </div>

          {task.due_date && (
            <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
              <Calendar className="h-3.5 w-3.5" />
              Échéance : {formatDate(task.due_date)}
            </div>
          )}

          <p className={`mt-2 text-sm text-slate-600 ${expanded ? "" : "line-clamp-2"}`}>
            {task.description}
          </p>
          {task.explanation && expanded && (
            <p className="mt-1 text-sm text-slate-400 italic">{task.explanation}</p>
          )}
          {task.description && task.description.length > 90 && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-xs font-medium text-violet-600 hover:underline"
            >
              {expanded ? "Réduire" : "Voir plus"}
            </button>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onArchive(task.id)}
            title="Archiver"
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
          >
            <Archive className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(task.id)}
            title="Supprimer"
            className="rounded-full p-2 text-slate-400 hover:bg-red-50 hover:text-red-500 transition"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Volontaires - avatars empilés, comme la liste des membres du casier */}
      <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center -space-x-2">
          {task.volunteers.length === 0 ? (
            <span className="text-xs text-slate-400">Personne assigné pour l'instant.</span>
          ) : (
            task.volunteers.map((v) => (
              <div key={v.id} className="group relative">
                <MemberAvatar member={v} size={30} />
                <span className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-800 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition">
                  {v.display_name || v.username}
                </span>
              </div>
            ))
          )}
          {task.max_volunteers && (
            <span className="ml-3 text-xs text-slate-400">
              {task.volunteers.length}/{task.max_volunteers}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {isVolunteer ? (
            <button
              type="button"
              onClick={() => onWithdraw(task.id)}
              className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-100 transition"
            >
              <UserMinus className="h-3.5 w-3.5" />
              Se retirer
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onVolunteer(task.id)}
              className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 transition"
            >
              <UserPlus className="h-3.5 w-3.5" />
              Se proposer
            </button>
          )}
          <NominateSelect task={task} members={members} onNominate={onNominate} />
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Page principale                                                        */
/* ---------------------------------------------------------------------- */

export default function QuarterlyTasksPage() {
  const [tasks, setTasks] = useState([]);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("tous");
  const [showArchived, setShowArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const currentUserId = api.currentUserId;

  const loadTasks = async () => {
    setLoading(true);
    try {
      const [taskRes, memberRes] = await Promise.all([
        api.get("/tasks/quarterly"),
        api.get("/members"),
      ]);
      setTasks(taskRes.data);
      setMembers(memberRes.data);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTasks();
  }, []);

  const filteredTasks = useMemo(() => {
    const query = normalizeText(search);
    return tasks
      .filter((t) => (showArchived ? true : !t.archived))
      .filter((t) => roleFilter === "tous" || t.role === roleFilter)
      .filter((t) => !query || normalizeText(t.title).includes(query));
  }, [tasks, search, roleFilter, showArchived]);

  const handleVolunteer = async (taskId) => {
    try {
      await api.post(`/tasks/quarterly/${taskId}/volunteer`);
      toast.success("Vous vous êtes proposé pour cette tâche.");
      loadTasks();
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleWithdraw = async (taskId) => {
    try {
      await api.post(`/tasks/quarterly/${taskId}/withdraw`);
      toast.success("Retrait confirmé.");
      loadTasks();
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleNominate = async (taskId, memberId) => {
    try {
      await api.post(`/tasks/quarterly/${taskId}/nominate`, { member_id: memberId });
      toast.success("Membre nommé.");
      loadTasks();
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleArchive = async (taskId) => {
    try {
      await api.post(`/tasks/quarterly/${taskId}/archive`);
      toast.success("Tâche archivée.");
      loadTasks();
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  };

  const handleDelete = async (taskId) => {
    if (!window.confirm("Supprimer définitivement cette tâche ?")) return;
    try {
      await api.delete(`/tasks/quarterly/${taskId}`);
      toast.success("Tâche supprimée.");
      loadTasks();
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      {/* En-tête façon "MODÉRATION" du casier : badge + titre + action principale */}
      <div className="flex items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center rounded-full bg-slate-900 text-white text-xs font-semibold tracking-wide px-3 py-1">
            TÂCHES
          </span>
          <h1 className="text-xl font-semibold text-slate-800">Tâches du trimestre</h1>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 rounded-full bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 transition"
        >
          <Plus className="h-4 w-4" />
          Nouvelle tâche
        </button>
      </div>

      {/* Barre de recherche + filtres, comme la barre de recherche du casier */}
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher une tâche…"
            className="w-full rounded-full border border-slate-200 bg-white pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-200"
          />
        </div>

        <div className="flex items-center gap-1.5">
          {Object.entries(ROLE_LABELS).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setRoleFilter(value)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                roleFilter === value
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-500 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
            showArchived
              ? "bg-slate-100 text-slate-600 border-slate-200"
              : "bg-white text-slate-400 border-slate-200 hover:bg-slate-50"
          }`}
        >
          <Archive className="h-3.5 w-3.5" />
          Archivées
        </button>
      </div>

      {/* Liste des tâches en cartes */}
      <div className="space-y-3">
        {loading ? (
          <div className="text-center text-sm text-slate-400 py-10">Chargement…</div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center text-sm text-slate-400 py-10 bg-white rounded-2xl border border-slate-100">
            Aucune tâche enregistrée pour ce trimestre.
          </div>
        ) : (
          filteredTasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              members={members}
              onVolunteer={handleVolunteer}
              onWithdraw={handleWithdraw}
              onNominate={handleNominate}
              onArchive={handleArchive}
              onDelete={handleDelete}
              currentUserId={currentUserId}
            />
          ))
        )}
      </div>

      {/* Placeholder de création — à relier à votre modal existant */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-2xl p-5 w-full max-w-md shadow-xl">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-800">Nouvelle tâche</h2>
              <button type="button" onClick={() => setShowCreate(false)}>
                <X className="h-4 w-4 text-slate-400" />
              </button>
            </div>
            <p className="text-sm text-slate-500">
              Branchez ici votre formulaire de création existant (titre, description, rôle,
              échéance, nombre de volontaires max).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
