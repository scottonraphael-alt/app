import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Bell, BookOpenCheck, GraduationCap, Check, CheckCheck, LogOut, Pencil, Monitor, Moon, Plus, Radio, Search, Star, Sun, X } from "lucide-react";

import { api } from "../../api/client";
import useTheme from "../../hooks/useTheme";
import { OPEN_EVENT } from "../command/CommandPalette";
import StatusPicker from "../team/StatusPicker";
import "./Topbar.css";

const FAVORITES_KEY = ["profile", "favorites"];
const NOTIFICATIONS_KEY = ["notifications"];

function useOutsideClose(ref, onClose) {
  useEffect(() => {
    const handler = (event) => {
      if (ref.current && !ref.current.contains(event.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onClose]);
}

function FavoritesBar() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const addRef = useRef(null);
  useOutsideClose(addRef, () => setAdding(false));

  const { data } = useQuery({
    queryKey: FAVORITES_KEY,
    queryFn: async () => (await api.get("/profile/me/favorites")).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const save = useMutation({
    mutationFn: async (favorites) => (await api.put("/profile/me/favorites", { favorites })).data,
    onSuccess: (payload) => queryClient.setQueryData(FAVORITES_KEY, payload),
    onError: () => queryClient.invalidateQueries({ queryKey: FAVORITES_KEY }),
  });

  if (!data) return <div className="tb-favorites" />;
  const byKey = Object.fromEntries(data.available.map((page) => [page.key, page]));
  const favorites = data.favorites.filter((key) => byKey[key]);
  const remaining = data.available.filter((page) => !favorites.includes(page.key));
  const commit = (next) => {
    queryClient.setQueryData(FAVORITES_KEY, { ...data, favorites: next, is_default: false });
    save.mutate(next);
  };
  const move = (index, delta) => {
    const next = [...favorites];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    commit(next);
  };

  return (
    <nav className="tb-favorites" aria-label="Favoris" data-testid="favorites-bar">
      <Star size={15} className="tb-star" aria-hidden="true" />
      {favorites.length === 0 && !editing && <span className="tb-hint">Aucun favori</span>}
      {favorites.map((key, index) => (
        <span className="tb-chip-wrap" key={key}>
          <NavLink className="tb-chip" end={byKey[key].path === "/"} to={byKey[key].path}>
            {byKey[key].label}
          </NavLink>
          {editing && (
            <span className="tb-chip-tools">
              <button type="button" aria-label={`Déplacer ${byKey[key].label} à gauche`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowLeft size={12} /></button>
              <button type="button" aria-label={`Déplacer ${byKey[key].label} à droite`} disabled={index === favorites.length - 1} onClick={() => move(index, 1)}><ArrowRight size={12} /></button>
              <button type="button" aria-label={`Retirer ${byKey[key].label}`} onClick={() => commit(favorites.filter((item) => item !== key))}><X size={12} /></button>
            </span>
          )}
        </span>
      ))}
      {editing && favorites.length < 12 && remaining.length > 0 && (
        <span className="tb-add" ref={addRef}>
          <button type="button" className="tb-chip tb-chip-add" onClick={() => setAdding((value) => !value)} aria-expanded={adding}>
            <Plus size={13} /> Ajouter
          </button>
          {adding && (
            <div className="tb-menu" role="menu">
              {remaining.map((page) => (
                <button key={page.key} type="button" role="menuitem" onClick={() => { commit([...favorites, page.key]); setAdding(false); }}>
                  {page.label}
                </button>
              ))}
            </div>
          )}
        </span>
      )}
      <button
        type="button" className="tb-icon-btn" onClick={() => { setEditing((value) => !value); setAdding(false); }}
        aria-label={editing ? "Terminer la modification des favoris" : "Modifier mes favoris"}
        title={editing ? "Terminer" : "Modifier mes favoris"}
      >
        {editing ? <Check size={15} /> : <Pencil size={14} />}
      </button>
    </nav>
  );
}

function NotificationBell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useOutsideClose(ref, () => setOpen(false));

  const { data } = useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: async () => (await api.get("/notifications")).data,
    refetchInterval: 60 * 1000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
  const readOne = useMutation({ mutationFn: (id) => api.post(`/notifications/${id}/read`), onSettled: refresh });
  const readAll = useMutation({ mutationFn: () => api.post("/notifications/read-all"), onSettled: refresh });

  const items = data?.items || [];
  const unread = data?.unread_count || 0;
  const noteClass = (item) => {
    if (item.type === "ticket_crisis") return " is-crisis";
    if (item.type === "handoff_urgent") return " is-urgent";
    return "";
  };
  const openItem = (item) => {
    if (!item.read_at) readOne.mutate(item.id);
    setOpen(false);
    if (item.link) navigate(item.link);
  };

  return (
    <div className="tb-bell" ref={ref}>
      <button
        type="button" className="tb-icon-btn" onClick={() => setOpen((value) => !value)}
        aria-label={unread ? `Notifications, ${unread} non lues` : "Notifications"} aria-expanded={open}
        data-testid="notifications-bell"
      >
        <Bell size={17} />
        {unread > 0 && <span className="tb-badge">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="tb-panel" role="dialog" aria-label="Notifications">
          <div className="tb-panel-head">
            <strong>Notifications</strong>
            <button type="button" className="tb-link" disabled={!unread} onClick={() => readAll.mutate()}>
              <CheckCheck size={14} /> Tout marquer comme lu
            </button>
          </div>
          {items.length === 0 ? (
            <p className="tb-empty">Rien de nouveau pour le moment.</p>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.id}>
                  <button type="button" className={`tb-note ${item.read_at ? "" : "is-unread"}${noteClass(item)}`} onClick={() => openItem(item)}>
                    <span className="tb-note-title">{item.title}</span>
                    {item.body && <span className="tb-note-body">{item.body}</span>}
                    <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</time>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="tb-panel-foot">
            <Link className="tb-link" to="/notifications" onClick={() => setOpen(false)}>Tout voir <ArrowRight size={13} aria-hidden="true" /></Link>
          </div>
        </div>
      )}
    </div>
  );
}

function LearningLinks() {
  const { data } = useQuery({
    queryKey: FAVORITES_KEY,
    queryFn: async () => (await api.get("/profile/me/favorites")).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const allowed = new Set((data?.available || []).map(page => page.key));
  return <>{[
    { key: "formations", path: "/staff/formations", label: "Mini formation", Icon: GraduationCap },
    { key: "fiches_reflexes", path: "/staff/fiches-reflexes", label: "Fiche réflexe", Icon: BookOpenCheck },
  ].filter(page => allowed.has(page.key)).map(({ key, path, label, Icon }) => (
    <Link key={key} className="tb-chip tb-learning" to={path} title={label} aria-label={label}><Icon size={16} aria-hidden="true" /><span>{label}</span></Link>
  ))}</>;
}

const THEME_META = {
  light: { Icon: Sun, label: "Thème clair", next: "sombre" },
  dark: { Icon: Moon, label: "Thème sombre", next: "système" },
  system: { Icon: Monitor, label: "Thème du système", next: "clair" },
};

function ThemeToggle() {
  const { preference, cycleTheme } = useTheme();
  const { Icon, label, next } = THEME_META[preference];
  return (
    <button
      type="button" className="tb-icon-btn" onClick={cycleTheme} data-testid="theme-toggle"
      aria-label={`${label}. Passer au thème ${next}`} title={`${label} (cliquer pour : ${next})`}
    >
      <Icon size={16} />
    </button>
  );
}

export default function Topbar({ helper, roleLabel, onLogout }) {
  return (
    <header className="tb-bar" data-testid="topbar">
      <FavoritesBar />
      <div className="tb-right">
        <button
          type="button" className="tb-icon-btn" onClick={() => window.dispatchEvent(new Event(OPEN_EVENT))}
          aria-label="Rechercher une page (Ctrl+K)" title="Rechercher (Ctrl+K)" data-testid="command-open"
        >
          <Search size={16} />
        </button>
        <StatusPicker />
        <ThemeToggle />
        <LearningLinks />
        <NotificationBell />
        {(helper || onLogout) && (
          <div className="tb-identity" data-testid="helper-identity">
            <Link className="tb-account" to="/profile" data-testid="helper-profile-link" title="Ouvrir mon profil">
              <span className="tb-avatar">
                {helper?.avatar_url ? <img src={helper.avatar_url} alt="" /> : <Radio size={13} />}
              </span>
              <span className="tb-account-text">
                <strong>{helper?.global_name || helper?.username}</strong>
                <small>{roleLabel}</small>
              </span>
            </Link>
            <button type="button" className="tb-icon-btn" aria-label="Se déconnecter" title="Se déconnecter" onClick={onLogout} data-testid="logout-button">
              <LogOut size={16} />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
