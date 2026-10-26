import { act } from "react";
import { createRoot } from "react-dom/client";
jest.mock("react-router-dom", () => ({
  useParams: () => ({ ticketId: "ticket" }), useNavigate: () => jest.fn(),
  Link: ({ children }) => <span>{children}</span>,
}), { virtual: true });
jest.mock("@/Casier.css", () => ({}), { virtual: true });
jest.mock("@/TicketWorkspace.css", () => ({}), { virtual: true });
import TicketWorkspacePage from "./TicketWorkspacePage";
import { api } from "../api/client";

jest.mock("../api/client", () => ({ api: { get: jest.fn() }, getErrorMessage: () => "Erreur" }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
global.IS_REACT_ACT_ENVIRONMENT = true;

it("charge les messages par page et ouvre le suivi", async () => {
  const ticket = { id: "ticket", member: { username: "Membre" }, status: "active", message_count: 51, created_at: "2026-10-01", transcript: [], notes_entries: [] };
  api.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith("/messages") ? {
    total: 51, messages: [{ id: `message-${options.params.page}`, content: `Page ${options.params.page}`, timestamp: "2026-10-01", author: { id: "1", username: "Membre" } }],
  } : ticket }));
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(<TicketWorkspacePage />));
  expect(api.get).toHaveBeenCalledWith("/tickets/ticket", { params: { include_transcript: false } });
  expect(container.textContent).toContain("Page 1 sur 2");
  await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Suivante").click());
  expect(container.textContent).toContain("Page 2 sur 2");
  expect(container.querySelector('[data-testid="transcript-message-message-2"]')).not.toBeNull();
  expect([...container.querySelectorAll("button")].find((b) => b.textContent === "Suivante").disabled).toBe(true);
  await act(async () => container.querySelector('[role="tab"][data-state="inactive"]').focus());
  expect(container.textContent).toContain("RÉSUMÉ CLAUDE");
  await act(async () => root.unmount());
  container.remove();
});
