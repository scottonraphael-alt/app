import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bell, Calendar, CalendarRange, ClipboardList, CornerDownLeft, FileText, FolderKanban, Gauge, Home, Inbox,
  LogOut, Moon, Search, Shield, Star, User, Users, Columns3, ListChecks, Keyboard, BarChart3, GanttChart, Heart,
  ClipboardCheck, CloudSun, BookOpenCheck, GraduationCap, Activity, Settings, Gavel,
} from "lucide-react";

import { api } from "../../api/client";
import useTheme from "../../hooks/useTheme";
import "./CommandPalette.css";

export const OPEN_EVENT = "iris-open-command";

function norm(text) {
  return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

// Score flou : sous-chaîne > sous-séquence ; -1 si aucun match.
export function fuzzyScore(query, label) {
  const q = norm(query).trim();
  if (!q) return 0;
  const t = norm(label);
  const at = t.indexOf(q);
  if (at >= 0) return 1000 - at;
  let i = 0;
  for (const ch of t) if (ch === q[i]) i += 1;
  return i === q.length ? 100 - t.length : -1;
}

const PAGE_ICONS = {
  accueil: Home, suivis: Inbox, archives: Inbox, ressources: FileText, coordination: Users,
  calendrier: Calendar, reunions: CalendarRange, taches: ClipboardList, casier: Shield, projets: FolderKanban,
  calendrier_projets: Calendar, passation: ClipboardList, notifications: Bell, charge: Gauge,
  rapports: FileText, membres: User, profil: User,
  kanban: Columns3, sondages: ListChecks, revue_ia: Keyboard, stats_moderation: BarChart3, chronologie: GanttChart,
  annuaire: Users, kudos: Heart, parcours_accueil: ClipboardCheck, meteo_equipe: CloudSun, fiches_reflexes: BookOpenCheck,
  formations: GraduationCap, sante_systeme: Activity, reglages: Settings, decisions: Gavel,
};

const TYPE_LABELS = {
  ticket: "Tickets", casier: "Casiers", projet: "Projets", tache: "Tâches",
  reunion: "Réunions", evenement: "Événements", ressource: "Ressources",
};

const RECENT_KEY = "iris.cmd.recents";
const RECENT_MAX = 5;

function readRecents() {
  try {
    const list = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(list) ? list.filter((r) => r && typeof r.id === "string" && typeof r.label === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function pushRecent(entry) {
  try {
    const next = [entry, ...readRecents().filter((r) => r.id !== entry.id)].slice(0, RECENT_MAX);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch { /* ignore */ }
}

const FOCUSABLE = "input, button:not(:disabled), [tabindex]:not([tabindex='-1'])";

export default function CommandPalette({ onLogout }) {
  const navigate = useNavigate();
  const { cycleTheme, preference } = useTheme();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialogRef = useRef(null);
  const inputRef = useRef(null);
  const returnFocus = useRef(null);

  const { data } = useQuery({
    queryKey: ["profile", "favorites"],
    queryFn: async () => (await api.get("/profile/me/favorites")).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const [results, setResults] = useState([]);

  useEffect(() => {
    const term = query.trim();
    if (!open || term.length < 2) { setResults([]); return undefined; }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await api.get("/search", { params: { q: term, limit: 20 }, signal: controller.signal });
        setResults(Array.isArray(response.data?.results) ? response.data.results : []);
      } catch {
        if (!controller.signal.aborted) setResults([]);
      }
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, open]);

  useEffect(() => {
    const onKey = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    const onOpen = () => setOpen(true);
    document.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      returnFocus.current = document.activeElement;
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    } else if (returnFocus.current?.focus) {
      returnFocus.current.focus();
    }
  }, [open]);

  const themeLabel = { light: "clair", dark: "sombre", system: "système" }[preference];
  const items = useMemo(() => {
    const pages = (data?.available || []).map((page) => ({
      id: `page-${page.key}`, label: page.label, hint: page.path, group: "Pages", icon: PAGE_ICONS[page.key] || Star,
      run: () => navigate(page.path),
    }));
    const actions = [{
      id: "theme", label: "Basculer le thème", hint: `Actuel : ${themeLabel}`, group: "Actions", keepOpen: false,
      run: cycleTheme,
    }];
    if (onLogout) actions.push({ id: "logout", label: "Se déconnecter", hint: "", group: "Actions", run: onLogout });
    const filter = (list) => list
      .map((item) => ({ item, score: fuzzyScore(query, item.label) }))
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => b.score - a.score)
      .map((entry) => entry.item);
    const found = results.filter((r) => r && r.url).map((r) => ({
      id: `res-${r.type}-${r.id}`, label: r.title, hint: r.subtitle || "", group: TYPE_LABELS[r.type] || "Résultats",
      path: r.url, run: () => navigate(r.url),
    }));
    const groups = [];
    found.forEach((item) => {
      if (!groups.includes(item.group)) groups.push(item.group);
    });
    const ordered = groups.flatMap((group) => found.filter((item) => item.group === group));
    const byId = new Map([...pages, ...actions].map((item) => [item.id, item]));
    const recents = query.trim() ? [] : readRecents().map((r) => {
      const known = byId.get(r.id);
      if (known) return { ...known, id: `recent-${known.id}`, group: "Récents" };
      if (r.path) return { id: `recent-${r.id}`, label: r.label, hint: "", group: "Récents", icon: Star, run: () => navigate(r.path) };
      return null;
    }).filter(Boolean);
    return [...recents, ...filter(pages), ...ordered, ...filter(actions)];
  }, [open, data, query, results, navigate, cycleTheme, onLogout, themeLabel]);

  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;

  const close = () => setOpen(false);
  const choose = (item) => {
    if (!item) return;
    close();
    if (item.id !== "logout" && !item.id.startsWith("recent-")) {
      const path = item.id.startsWith("res-") ? item.path : undefined;
      pushRecent({ id: item.id, label: item.label, path });
    }
    item.run();
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") { event.preventDefault(); close(); }
    else if (event.key === "ArrowDown") { event.preventDefault(); setActive((i) => (items.length ? (i + 1) % items.length : 0)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => (items.length ? (i - 1 + items.length) % items.length : 0)); }
    else if (event.key === "Enter") { event.preventDefault(); choose(items[active]); }
    else if (event.key === "Tab") {
      const nodes = dialogRef.current?.querySelectorAll(FOCUSABLE);
      if (!nodes?.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  };

  const activeId = items[active] ? `cmd-opt-${items[active].id}` : undefined;
  return (
    <div className="cmd-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <div className="cmd-dialog" role="dialog" aria-modal="true" aria-label="Palette de commandes" ref={dialogRef} onKeyDown={onKeyDown}>
        <div className="cmd-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="Aller à une page ou lancer une action…" aria-label="Rechercher"
            role="combobox" aria-expanded="true" aria-controls="cmd-list" aria-activedescendant={activeId} autoComplete="off"
          />
          <kbd>Échap</kbd>
        </div>
        <ul id="cmd-list" role="listbox" className="cmd-list">
          {items.length === 0 && <li className="cmd-empty">Aucun résultat.</li>}
          {items.map((item, index) => (
            <Fragment key={item.id}>
            {(index === 0 || items[index - 1].group !== item.group) && (
              <li role="presentation" className="cmd-heading">{item.group}</li>
            )}
            <li id={`cmd-opt-${item.id}`} role="option" aria-selected={index === active}
              className={`cmd-item ${index === active ? "is-active" : ""}`}
              onMouseEnter={() => setActive(index)} onClick={() => choose(item)}
            >
              <span className="cmd-icon" aria-hidden="true">
                {item.id === "theme" ? <Moon size={15} /> : item.id === "logout" ? <LogOut size={15} /> : item.icon ? <item.icon size={15} /> : <CornerDownLeft size={15} />}
              </span>
              <span className="cmd-label">{item.label}</span>
              {item.hint && item.id.startsWith("res-") && <span className="cmd-group">{item.hint}</span>}
            </li>
            </Fragment>
          ))}
        </ul>
        <div className="cmd-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> naviguer</span><span><kbd>Entrée</kbd> ouvrir</span></div>
      </div>
    </div>
  );
}
