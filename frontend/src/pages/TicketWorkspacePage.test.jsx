import { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock("react-router-dom", () => ({
  useParams: () => ({ ticketId: "ticket" }), useNavigate: () => jest.fn(),
  Link: ({ children }) => <span>{children}</span>,
}), { virtual: true });
jest.mock("@/TicketWorkspace.css", () => ({}), { virtual: true });
import TicketWorkspacePage from "./TicketWorkspacePage";
import { api } from "../api/client";

jest.mock("../api/client", () => ({ api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() }, getErrorMessage: () => "Erreur" }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
global.IS_REACT_ACT_ENVIRONMENT = true;

let container, root, ticket;
beforeEach(async () => {
  ticket = { id: "ticket", member: { id: "member", username: "Membre" }, status: "active", message_count: 51, created_at: "2026-10-01", transcript: [], notes_entries: [] };
  api.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith("/messages") ? {
    total: 51, messages: [{ id: `message-${options.params.page}`, content: `Page ${options.params.page}`, timestamp: "2026-10-01", author: { id: "member", username: "Membre" } }],
  } : ticket }));
  api.patch.mockImplementation((url, data) => Promise.resolve({ data: { ...ticket, ...data } }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<TicketWorkspacePage />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.clearAllMocks();
});
const click = async (selector) => act(async () => container.querySelector(selector).click());
const tab = async (value) => act(async () => container.querySelector(`[role="tab"][id$="trigger-${value}"]`).focus());
const type = async (selector, value) => act(async () => {
  const element = container.querySelector(selector);
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value").set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
});

it("pagine la conversation tout en gardant le résumé visible", async () => {
  expect(api.get).toHaveBeenCalledWith("/tickets/ticket", { params: { include_transcript: false } });
  await click('[aria-label="Page suivante"]');
  expect(container.querySelector('[aria-label="Page de messages"]').value).toBe("2");
  expect(container.querySelector('[data-testid="transcript-message-message-2"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Page suivante"]').disabled).toBe(true);
  expect(container.textContent).toContain("Synthèse du dossier");
  expect(container.querySelector('[data-testid="transcript-panel"]')).not.toBeNull();
});

it("ouvre la rédaction à la demande et conserve le brouillon entre les onglets", async () => {
  await tab("notes");
  expect(container.querySelector('[data-testid="new-ticket-note-form"]')).toBeNull();
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent.trim() === 'Ajouter').click());
  await type('#tw-note-title', 'Mon observation');
  await type('#tw-note-content', 'Une note à conserver');
  await tab("resume");
  await tab("notes");
  expect(container.querySelector('#tw-note-title').value).toBe('Mon observation');
  expect(container.querySelector('#tw-note-content').value).toBe('Une note à conserver');
});

it("enregistre les repères et indique les modifications en attente", async () => {
  expect(container.querySelector('[data-testid="save-ticket-button"]').disabled).toBe(true);
  await tab("reperes");
  await type('#tw-person-triggers', 'Prendre le temps');
  expect(container.textContent).toContain('Modifications non enregistrées');
  await click('[data-testid="save-ticket-button"]');
  expect(api.patch).toHaveBeenCalledWith('/tickets/ticket', expect.objectContaining({ person_triggers: 'Prendre le temps' }));
  expect(container.querySelector('[data-testid="save-ticket-button"]').disabled).toBe(true);
});
