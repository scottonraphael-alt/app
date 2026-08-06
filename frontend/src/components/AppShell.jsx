import {
  Archive, BookOpenText, CalendarDays, ChevronDown, FileStack,
  FolderKanban, Grid2X2, ClipboardList, LayoutDashboard, LogOut, RadioTower, Users,
} from "lucide-react";
import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import logo from "../assets/logo.png";

function highestRoleLabel({ isResponsable, isAdmin, isAnimateur, isOperateur, isStaff, isHelper }) {
  if (isResponsable) return "Responsable";
  if (isAdmin) return "Coordinateur";
  if (isOperateur) return "Opérateur";
  if (isAnimateur) return "Animateur";
  if (isHelper) return "Helper";
  if (isStaff) return "Staff";
  return "Membre";
}

export default function AppShell({
  children, helper, tickets, onLogout,
  isAdmin, isStaff, isResponsable, isAnimateur, isOperateur, isHelper,
}) {
    const [isResponsableMenuOpen, setIsResponsableMenuOpen] = useState(true);
  const [isHelperMenuOpen, setIsHelperMenuOpen] = useState(true);
  const [isStaffMenuOpen, setIsStaffMenuOpen] = useState(true);
  const [isAnimateurMenuOpen, setIsAnimateurMenuOpen] = useState(true);
   const [isOpMenuOpen, setIsOpMenuOpen] = useState(true);

  const roleLabel = highestRoleLabel({ isAdmin, isStaff, isOperateur, isResponsable, isAnimateur, isHelper });

  return (
    <div className="app-shell" data-testid="iris-application">
      <aside className="sidebar nano-sidebar" data-testid="main-navigation">
        <Link className="brand nano-brand" to="/" data-testid="iris-home-link">
          <img src={logo} alt="Iris" data-testid="iris-logo" />
        </Link>

        <nav className="sidebar-nav" aria-label="Navigation principale">


{(isResponsable) && (
  <div className="menu-group" data-testid="staff-menu-group">
    <button
      className="helper-menu-trigger"
      type="button"
      onClick={() => setIsResponsableMenuOpen((current) => !current)}
      aria-expanded={isResponsableMenuOpen}
      data-testid="staff-menu-toggle"
    >
      <Users size={18} />
      <span>Responsable</span>
      <ChevronDown className={isResponsableMenuOpen ? "is-open" : ""} size={16} />
    </button>
    <div className={`helper-menu-links ${isResponsableMenuOpen ? "is-open" : ""}`} data-testid="responsable-menu-links">
      <NavLink className="nav-link" to="/responsable/auth-logs" data-testid="responsable-logs" title="Logs">
        <FileStack size={18} /> <span>Logs</span>
      </NavLink>
    </div>
  </div>
)}


          
          {(isStaff || isResponsable) && (
  <div className="menu-group" data-testid="staff-menu-group">
    <button
      className="helper-menu-trigger"
      type="button"
      onClick={() => setIsStaffMenuOpen((current) => !current)}
      aria-expanded={isStaffMenuOpen}
      data-testid="staff-menu-toggle"
    >
      <Users size={18} />
      <span>Staff</span>
      <ChevronDown className={isStaffMenuOpen ? "is-open" : ""} size={16} />
    </button>
    <div className={`helper-menu-links ${isStaffMenuOpen ? "is-open" : ""}`} data-testid="staff-menu-links">
      <NavLink className="nav-link" to="/staff/calendrier" data-testid="staff-absences-link" title="Calendrier">
        <CalendarDays size={18} /> <span>Calendrier</span>
      </NavLink>
      <NavLink className="nav-link" to="/staff/meetings" data-testid="staff-meetings-link" title="Résumés de réunions">
        <FileStack size={18} /> <span>Réunions</span>
      </NavLink>
      <NavLink className="nav-link" to="/staff/taches" data-testid="staff-tasks-link" title="Tâches trimestrielles">
        <ClipboardList size={18} /> <span>Tâches</span>
      </NavLink>
    </div>
  </div>
)}
{(isOperateur || isResponsable) && (
  <div className="menu-group" data-testid="staff-menu-group">
    <button
      className="helper-menu-trigger"
      type="button"
      onClick={() => setIsOpMenuOpen((current) => !current)}
      aria-expanded={isOpMenuOpen}
      data-testid="op-menu-toggle"
    >
      <Users size={18} />
      <span>Opérateur</span>
      <ChevronDown className={isOpMenuOpen ? "is-open" : ""} size={16} />
    </button>
    <div className={`helper-menu-links ${isOpMenuOpen ? "is-open" : ""}`} data-testid="op-menu-links">
      <NavLink className="nav-link" to="/moderation/casiers" data-testid="casier" title="Casier">
        <FileStack size={18} /> <span>Casiers</span>
      </NavLink>
    </div>
  </div>
)}
          {(isAnimateur || isResponsable) && (
            <div className="menu-group" data-testid="animateur-menu-group">
              <button
                className="helper-menu-trigger"
                type="button"
                onClick={() => setIsAnimateurMenuOpen((current) => !current)}
                aria-expanded={isAnimateurMenuOpen}
                data-testid="animateur-menu-toggle"
              >
                <FolderKanban size={18} />
                <span>Animateur</span>
                <ChevronDown className={isAnimateurMenuOpen ? "is-open" : ""} size={16} />
              </button>
              <div className={`helper-menu-links ${isAnimateurMenuOpen ? "is-open" : ""}`} data-testid="animateur-menu-links">
                <NavLink className="nav-link" to="/animateur/projects" data-testid="animateur-projects-link" title="Projets">
                  <FolderKanban size={18} /> <span>Projets</span>
                </NavLink>
                <NavLink className="nav-link" to="/animateur/calendrier" data-testid="animateur-projects-link" title="Calendrier">
                  <FolderKanban size={18} /> <span>Calendrier</span>
                </NavLink>
              </div>
            </div>
          )}

          <div className="menu-group" data-testid="helper-menu-group">
            <button
              className="helper-menu-trigger"
              type="button"
              onClick={() => setIsHelperMenuOpen((current) => !current)}
              aria-expanded={isHelperMenuOpen}
              data-testid="helper-menu-toggle"
            >
              <RadioTower size={18} />
              <span>Helper</span>
              <ChevronDown className={isHelperMenuOpen ? "is-open" : ""} size={16} />
            </button>
            <div className={`helper-menu-links ${isHelperMenuOpen ? "is-open" : ""}`} data-testid="helper-menu-links">
              <NavLink end className="nav-link" to="/" data-testid="active-tickets-link" title="Dossiers actifs">
                <Grid2X2 size={18} /> <span>Suivis</span>
              </NavLink>
              <NavLink className="nav-link" to="/archives" data-testid="archives-link" title="Archives">
                <Archive size={18} /> <span>Archives</span>
              </NavLink>
              <NavLink className="nav-link" to="/resources" data-testid="sidebar-resources-link" title="Ressources">
                <BookOpenText size={18} /> <span>Ressources</span>
              </NavLink>
              {isAdmin && (
                <NavLink className="nav-link" to="/admin" data-testid="admin-panel-link" title="Vue administrateur">
                  <LayoutDashboard size={18} /> <span>Coordination</span>
                </NavLink>
              )}
            </div>
          </div>
        </nav>

        <div className="sidebar-bottom">
          <div className="helper-identity" data-testid="helper-identity">
            <Link className="helper-account-link" to="/profile" data-testid="helper-profile-link" title="Ouvrir mon profil">
              <span className="helper-avatar">
                {helper?.avatar_url ? <img src={helper.avatar_url} alt="" /> : <RadioTower size={15} />}
              </span>
              <span>
                <strong>{helper?.global_name || helper?.username}</strong>
                <small>{roleLabel}</small>
              </span>
            </Link>
            <button
              aria-label="Se déconnecter"
              className="icon-button"
              onClick={onLogout}
              title="Se déconnecter"
              type="button"
              data-testid="logout-button"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <main className="app-main">{children}</main>
    </div>
  );
}
