import { act } from "react";
import { createRoot } from "react-dom/client";
import DashboardPage from "./DashboardPage";

jest.mock("react-router-dom", () => ({
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
}), { virtual: true });
jest.mock("@/TicketList.css", () => ({}), { virtual: true });
jest.mock("../utils/ticketEvents", () => ({
  ticketEvent: jest.fn(), ATTENTION_LABELS: { inactive: "Sans suivi depuis 7 jours" },
}));
global.IS_REACT_ACT_ENVIRONMENT = true;

it("limite la vue À traiter aux dossiers ouverts concernés et affiche leur motif", async () => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const base = { member: { username: "Membre" }, updated_at: "2026-10-26", status: "active" };
  try {
    await act(async () => root.render(<DashboardPage tickets={[
      { ...base, id: "late", needs_attention: true, attention_reasons: ["inactive"] },
      { ...base, id: "current", needs_attention: false },
      { ...base, id: "archive", status: "archived", needs_attention: true },
    ]} />));
    const filter = [...container.querySelectorAll("button")].find(button => button.textContent.startsWith("À traiter"));
    expect(filter.textContent).toContain("1");
    await act(async () => filter.click());
    expect(container.querySelector('[data-testid="ticket-row-late"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="ticket-row-current"]')).toBeNull();
    expect(container.querySelector('[data-testid="ticket-row-archive"]')).toBeNull();
    expect(container.textContent).toContain("Sans suivi depuis 7 jours");
    await act(async () => [...container.querySelectorAll("button")].find(button => button.textContent === "Tous les suivis").click());
    expect(container.querySelector('[data-testid="ticket-row-current"]')).not.toBeNull();
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
