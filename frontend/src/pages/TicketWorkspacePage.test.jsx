import { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock("react-router-dom", () => ({
  useParams: () => ({ ticketId: "ticket" }), useNavigate: () => jest.fn(),
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
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
  api.post.mockResolvedValue({ data: ticket });
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
  expect(api.post).toHaveBeenCalledWith("/tickets/ticket/view");
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


it("masque le message initial du bot sans masquer ceux des autres pages", async () => {
  const message = (id, isBot) => ({ id, content: id, timestamp: "2026-10-01", author: { id: isBot ? "bot" : "member", username: isBot ? "Bot" : "Membre", is_bot: isBot } });
  api.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith("/messages") ? {
    total: 51,
    messages: options.params.page === 1 ? [message("ouverture-v2", true), message("echange", false), message("autre-bot", true)] : [message("bot-page-2", true)],
  } : ticket }));
  await click('[aria-label="Page suivante"]');
  expect(container.querySelector('[data-testid="transcript-message-bot-page-2"]')).not.toBeNull();
  await click('[aria-label="Page précédente"]');
  expect(container.querySelector('[data-testid="transcript-message-ouverture-v2"]')).toBeNull();
  expect(container.querySelector('[data-testid="transcript-message-echange"]')).not.toBeNull();
  expect(container.querySelector('[data-testid="transcript-message-autre-bot"]')).not.toBeNull();
});

it("affiche un état vide si seul le message d’ouverture existe", async () => {
  api.get.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/messages") ? {
    total: 1, messages: [{ id: "ouverture", content: "Message V2", timestamp: "2026-10-01", author: { id: "bot", username: "Bot", is_bot: true } }],
  } : ticket }));
  await click('[data-testid="sync-ticket-button"]');
  expect(container.querySelector('[data-testid="empty-transcript"]')).not.toBeNull();
  expect(container.querySelector('[data-testid="transcript-message-ouverture"]')).toBeNull();
});

it("utilise la copie d’avatar de l’API et affiche une initiale si l’image manque", async () => {
  const avatar = `/api/tickets/avatars/${"a".repeat(64)}`;
  api.get.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/messages") ? {
    total: 1, messages: [{ id: "portrait", content: "Bonjour", timestamp: "2026-10-01", author: { id: "member", username: "Membre", avatar_url: avatar } }],
  } : ticket }));
  await click('[data-testid="sync-ticket-button"]');
  const image = container.querySelector('.tw-author-avatar img');
  expect(image.getAttribute('src')).toContain(avatar);
  await act(async () => image.dispatchEvent(new Event('error')));
  expect(container.querySelector('.tw-author-avatar img')).toBeNull();
  expect(container.querySelector('.tw-author-avatar').textContent).toBe('M');
});


it("recherche dans toutes les pages et ouvre le message trouvé", async () => {
  api.get.mockImplementation((url, options) => Promise.resolve({ data: url.endsWith('/search') ? {
    total: 1, page: 1, items: [{ message_id: 'message-2', message_page: 2, author_name: 'Membre', timestamp: '2026-10-01', excerpt: 'Un souvenir retrouvé' }],
  } : { total: 51, messages: [{ id: 'message-2', content: 'Un souvenir retrouvé', timestamp: '2026-10-01', author: { id: 'member', username: 'Membre' } }] } }));
  await click('button[aria-expanded]');
  await type('[aria-label="Rechercher dans toute la conversation"]', 'souvenir');
  await act(async () => container.querySelector('.tw-search-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(api.get).toHaveBeenCalledWith('/tickets/ticket/messages/search', expect.objectContaining({ params: expect.objectContaining({ q: 'souvenir' }) }));
  await click('.tw-search-result');
  expect(container.querySelector('[aria-label="Page de messages"]').value).toBe('2');
  expect(container.querySelector('#tw-message-message-2').className).toContain('is-search-hit');
});

it("signale une interruption du flux IA sans annoncer une réussite", async () => {
  const { toast } = require("sonner");
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => ({ done: true }) }) } });
  const originalDecoder = global.TextDecoder;
  global.TextDecoder = class { decode(value) { return value; } };
  try {
    await click('[data-testid="generate-ai-summary-button"]');
    expect(toast.success).not.toHaveBeenCalledWith("Résumé Claude enregistré.");
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("connexion a été interrompue"));
  } finally { global.fetch = originalFetch; global.TextDecoder = originalDecoder; }
});

it("enregistre la confirmation du résumé même si le message arrive en plusieurs morceaux", async () => {
  const { toast } = require("sonner");
  const originalFetch = global.fetch, originalDecoder = global.TextDecoder;
  const payload = JSON.stringify({ context: "Résumé vérifié", expressed_needs: "Besoins", actions: "Actions", next_follow_up: "Suivi" });
  const chunks = ["event: com", `plete\ndata: ${payload}\n\n`];
  global.TextDecoder = class { decode(value) { return value; } };
  global.fetch = jest.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read: async () => chunks.length ? ({ done: false, value: chunks.shift() }) : ({ done: true }) }) } });
  try {
    await click('[data-testid="generate-ai-summary-button"]');
    expect(toast.success).toHaveBeenCalledWith("Résumé Claude enregistré.");
    expect(container.textContent).toContain("Résumé vérifié");
    expect(toast.error).not.toHaveBeenCalled();
  } finally { global.fetch = originalFetch; global.TextDecoder = originalDecoder; }
});
