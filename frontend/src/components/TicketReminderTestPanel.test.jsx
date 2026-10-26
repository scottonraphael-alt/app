import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TicketReminderTestPanel from "./TicketReminderTestPanel";
import { api } from "../api/client";

jest.mock("../api/client", () => ({ api: { post: jest.fn() }, getErrorMessage: () => "Discord indisponible" }));
global.IS_REACT_ACT_ENVIRONMENT = true;
let root, container, queryClient;
beforeEach(async () => {
  queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<QueryClientProvider client={queryClient}><TicketReminderTestPanel /></QueryClientProvider>));
});
afterEach(async () => {
  await act(async () => root.unmount());
  queryClient.clear();
  container.remove();
  jest.clearAllMocks();
});
const flush = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });

it("envoie uniquement après clic puis affiche le résultat et le lien Discord", async () => {
  expect(api.post).not.toHaveBeenCalled();
  api.post.mockResolvedValue({ data: { ticket_count: 2, helper_count: 1, message_urls: ["https://discord.com/channels/1/2/3"] } });
  await act(async () => container.querySelector("button").click());
  await flush();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith("/admin/ticket-reminders/test");
  expect(container.textContent).toContain("2 dossier(s), 1 helper(s)");
  expect(container.querySelector("a").href).toBe("https://discord.com/channels/1/2/3");
  expect(container.querySelector("button").disabled).toBe(true);
});

it("rend l’erreur visible sans annoncer un envoi réussi", async () => {
  api.post.mockRejectedValue(new Error("Échec"));
  await act(async () => container.querySelector("button").click());
  await flush();
  expect(container.querySelector('[role="alert"]').textContent).toBe("Discord indisponible");
  expect(container.querySelector('[role="status"]')).toBeNull();
  expect(container.querySelector("button").disabled).toBe(false);
});
