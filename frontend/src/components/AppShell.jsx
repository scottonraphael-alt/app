import { useEffect, useRef } from "react";
import Topbar from "./topbar/Topbar";
import CommandPalette from "./command/CommandPalette";
import AnnouncementBanner from "./responsable/AnnouncementBanner";
import { PageMemoryProvider } from "./ux/PageMemory";
import UxLayer from "./ux/UxLayer";
import useSurfaceMotion from "./motion/useSurfaceMotion";

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
  const route = useRef(null);
  useSurfaceMotion(route);
  useEffect(() => {
    document.body.classList.add("iris-ux-active");
    const viewport = document.querySelector('meta[name="viewport"]');
    const previousViewport = viewport?.getAttribute('content');
    const baseViewport = previousViewport || 'width=device-width, initial-scale=1';
    const safeViewport = /viewport-fit\s*=/.test(baseViewport)
      ? baseViewport.replace(/viewport-fit\s*=[^,]*/g, 'viewport-fit=cover')
      : `${baseViewport}, viewport-fit=cover`;
    viewport?.setAttribute('content', safeViewport);
    return () => {
      document.body.classList.remove("iris-ux-active");
      if (viewport?.getAttribute('content') === safeViewport) {
        if (previousViewport === null) viewport.removeAttribute('content');
        else viewport.setAttribute('content', previousViewport);
      }
    };
  }, []);
  const roleLabel = highestRoleLabel({ isAdmin, isStaff, isOperateur, isResponsable, isAnimateur, isHelper });

  return (
    <PageMemoryProvider key={helper?.id || "session"}><div className="app-shell iris-ui" data-testid="iris-application">
      <main className="app-main">
        <Topbar helper={helper} roleLabel={roleLabel} onLogout={onLogout} />
        <AnnouncementBanner />
        <div className="iris-route" ref={route}>{children}</div>
        <CommandPalette onLogout={onLogout} />
        <UxLayer />
      </main>
    </div></PageMemoryProvider>
  );
}
