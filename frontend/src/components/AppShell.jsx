import Topbar from "./topbar/Topbar";
import CommandPalette from "./command/CommandPalette";

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
  const roleLabel = highestRoleLabel({ isAdmin, isStaff, isOperateur, isResponsable, isAnimateur, isHelper });

  return (
    <div className="app-shell" data-testid="iris-application">
      <main className="app-main">
        <Topbar helper={helper} roleLabel={roleLabel} onLogout={onLogout} />
        {children}
        <CommandPalette onLogout={onLogout} />
      </main>
    </div>
  );
}
