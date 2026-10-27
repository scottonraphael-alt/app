import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { api } from "../../../api/client";
import MeetingEditor from "./MeetingEditor";

jest.mock("../../../api/client", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn(), defaults: { baseURL: "/api" } },
  getErrorMessage: () => "Erreur",
}));
jest.mock(
  "react-router-dom",
  () => ({
    Link: ({ to, children, ...props }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    useNavigate: () => jest.fn(),
    useSearchParams: () => [new URLSearchParams(), jest.fn()],
  }),
  { virtual: true },
);
// Jest de CRA ne connaît pas l'alias « @ » utilisé par les briques communes.
jest.mock("@/Agenda.css", () => ({}), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock("../../TiptapSummaryEditor", () => {
  const React = require("react");
  const Editor = ({ value, onChange }) => (
    <textarea aria-label="éditeur" value={value} onChange={(event) => onChange(event.target.value)} />
  );
  return {
    __esModule: true,
    default: Editor,
    contentToPlainText: (value) => String(value || ""),
    countWords: (text) => (String(text).trim() ? String(text).trim().split(/\s+/).length : 0),
    readingMinutes: () => 1,
  };
});
jest.mock("../../SummaryReader", () => ({ __esModule: true, default: ({ content }) => <div data-testid="lecture">{content}</div> }));
jest.mock("../meetings/MeetingDialog", () => ({ __esModule: true, default: () => null }));
jest.mock("../PeoplePicker", () => ({ __esModule: true, default: () => <span>responsable</span> }));

global.IS_REACT_ACT_ENVIRONMENT = true;

const person = { id: "400000000000000003", username: "staff", display_name: "Inès", avatar_url: null };

function detail(extra = {}) {
  return {
    id: "m1",
    title: "Point modération",
    meeting_date: "2026-10-22",
    start_time: "21:00",
    end_time: null,
    location: "Vocal Staff",
    phase: "a_rediger",
    status: "a_rediger",
    is_locked: false,
    cancelled: false,
    author: person,
    agenda_items: [{ id: "a1", title: "Tour de table", done: false }],
    content_markdown: "",
    decisions: [],
    action_items: [
      { id: "x1", text: "Mettre à jour le planning", assignee: person, due_date: "2026-10-30", done: false },
      { id: "x2", text: "Prévenir l'équipe", assignee: null, due_date: null, done: false },
    ],
    participants: [{ ...person, attendance: "invite" }],
    participants_absent: [],
    reminders: { enabled: false, offsets: [], ping_role: false, schedule: [] },
    revision: 7,
    created_at: "2026-10-20T18:00:00+00:00",
    updated_at: "2026-10-23T09:10:00+00:00",
    updated_by: person,
    can_edit: true,
    viewer: { id: "400000000000000077", is_responsable: false },
    ...extra,
  };
}

async function mount(data) {
  api.get.mockResolvedValue({ data });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MeetingEditor meetingId="m1" />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  // Horloge simulée seulement après le chargement : les minuteries de la file d'envoi deviennent contrôlables.
  jest.useFakeTimers();
  return { container, root };
}

function type(node, value) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  setter.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("page réunion", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.values(api).forEach((fn) => fn.mockReset && fn.mockReset());
  });
  afterEach(() => {
    jest.useRealTimers();
    document.body.innerHTML = "";
  });

  it("enregistre le compte-rendu après 1,2 s avec la révision attendue", async () => {
    api.patch.mockResolvedValue({ data: { id: "m1", revision: 8, updated_at: "2026-10-25T19:00:00+00:00", status: "redige", phase: "redige", word_count: 3 } });
    const { container, root } = await mount(detail());
    expect(container.querySelector("h1 input").value).toBe("Point modération");
    await act(async () => type(container.querySelector("textarea"), "Bonjour à tous"));
    expect(container.textContent).toContain("Modifications en attente");
    await act(async () => {
      jest.advanceTimersByTime(1300);
    });
    expect(api.patch).toHaveBeenCalledTimes(1);
    const [url, body, options] = api.patch.mock.calls[0];
    expect(url).toBe("/agenda/meetings/m1");
    expect(body).toEqual({ expected_revision: 7, content_markdown: "Bonjour à tous" });
    expect(options.params).toEqual({ minimal: true });
    expect(container.textContent).toContain("Enregistré");
    await act(async () => root.unmount());
  });

  it("n'envoie done que pour l'action cochée, par l'enregistrement automatique", async () => {
    api.patch.mockResolvedValue({ data: { id: "m1", revision: 8, status: "a_rediger", phase: "a_rediger", word_count: 0 } });
    const { container, root } = await mount(detail());
    const box = container.querySelector('input[aria-label="Action faite : Mettre à jour le planning"]');
    await act(async () => box.click());
    await act(async () => {
      jest.advanceTimersByTime(700);
    });
    expect(api.patch).toHaveBeenCalledTimes(1);
    const [url, body] = api.patch.mock.calls[0];
    expect(url).toBe("/agenda/meetings/m1");
    expect(body.action_items).toEqual([
      { id: "x1", text: "Mettre à jour le planning", assignee_id: person.id, due_date: "2026-10-30", done: true },
      { id: "x2", text: "Prévenir l'équipe", assignee_id: null, due_date: null },
    ]);
    await act(async () => root.unmount());
  });

  it("affiche le conflit de révision et laisse le choix", async () => {
    api.patch.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Conflit", code: "revision_conflict", current_revision: 9, updated_at: "2026-10-25T19:40:00+00:00", updated_by: person },
      },
    });
    const { container, root } = await mount(detail());
    await act(async () => type(container.querySelector("textarea"), "Texte"));
    await act(async () => {
      jest.advanceTimersByTime(1300);
    });
    expect(container.textContent).toContain("Ce compte-rendu a été modifié par Inès");
    expect(container.textContent).toContain("Recharger leur version");
    expect(container.textContent).toContain("Garder ma version");
    await act(async () => root.unmount());
  });

  it("réunion verrouillée : lecture seule, action cochée par l'endpoint dédié", async () => {
    api.patch.mockResolvedValue({
      data: { meeting_id: "m1", revision: 7, item: { id: "x1", text: "Mettre à jour le planning", assignee: person, due_date: "2026-10-30", done: true, done_at: "2026-10-25T19:05:00Z", done_by: person } },
    });
    const { container, root } = await mount(detail({ is_locked: true, can_edit: false, locked_by: person, locked_at: "2026-10-23T09:00:00+00:00" }));
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain("Ce compte-rendu est verrouillé par Inès");
    const box = container.querySelector('input[aria-label="Action faite : Mettre à jour le planning"]');
    await act(async () => box.click());
    expect(api.patch).toHaveBeenCalledWith("/agenda/meetings/m1/actions/x1", { done: true });
    await act(async () => root.unmount());
  });
});
