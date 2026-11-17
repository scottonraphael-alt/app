import { useEffect } from "react";
import Topbar from "./topbar/Topbar";
import CommandPalette from "./command/CommandPalette";
import AnnouncementBanner from "./responsable/AnnouncementBanner";
import UxLayer from "./ux/UxLayer";

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
  useEffect(() => {
    document.body.classList.add("iris-ux-active");
    return () => document.body.classList.remove("iris-ux-active");
  }, []);
  const roleLabel = highestRoleLabel({ isAdmin, isStaff, isOperateur, isResponsable, isAnimateur, isHelper });

  return (
    <div className="app-shell iris-ui" data-testid="iris-application">
      <main className="app-main">
        <Topbar helper={helper} roleLabel={roleLabel} onLogout={onLogout} />
        <AnnouncementBanner />
        {children}
        <CommandPalette onLogout={onLogout} />
        <UxLayer />
      </main>
    </div>
  );
}
