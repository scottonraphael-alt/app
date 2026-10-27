import { act } from "react";
import { createRoot } from "react-dom/client";
import ServerStatisticsPage from "./ServerStatisticsPage";
import { api } from "../api/client";

jest.mock("react-router-dom", () => ({ Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("@/ServerStatistics.css", () => ({}), { virtual: true });
jest.mock("../api/client", () => ({ api: { get: jest.fn() }, getErrorMessage: () => "Erreur de collecte" }));
jest.mock("../components/statistics/StatisticsChart", () => () => <div data-testid="echarts-placeholder" />);
global.IS_REACT_ACT_ENVIRONMENT = true;
let root, container;
const data = {
  totals: { messages:12, active_members:3, active_channels:2, attachments:1, characters:84 },
  daily:[{day:"2026-10-27",messages:12}], members:[{id:"1",name:"Alex",messages:12}],
  channels:[{id:"2",name:"discussion",messages:12}],category_totals:[],
  categories:[{id:"1499495158469758976",name:"Soutien",internal:true}],
  available_channels:[{id:"2",name:"discussion",category_id:"1499495158469758976"}],
  charts:{
    timeline:[{id:"day",label:"27/10/2026",from:"2026-10-27",to:"2026-10-27",messages:12,coverage:1,previous_messages:null}],
    heatmap:[{weekday:1,hour:12,messages:12,coverage:1,observed_hours:1,possible_hours:1}],
    hour_profile:[{hour:12,messages:12,coverage:1}],lengths:[{id:"short",label:"0–40 caractères",messages:12,share:100}],
    coverage:{ratio:1,observed_hours:12,possible_hours:12},comparison:null,
  },
  collection:{enabled:true,connected:true,started_at:"2026-10-27T00:00:00Z",pending_messages:0,registry_days:30,sessions:[]},
};
beforeEach(async () => {
  localStorage.clear();
  api.get.mockResolvedValue({data});
  container=document.createElement("div"); document.body.appendChild(container);
  root=createRoot(container);
  await act(async () => root.render(<ServerStatisticsPage />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.clearAllMocks(); });

it("affiche les premiers compteurs et le retour vers le NewDashboard", () => {
  expect(container.textContent).toContain("Bot connecté");
  expect(container.textContent).toContain("Membres actifs");
  expect(container.textContent).toContain("Alex");
  expect(container.querySelector('a').getAttribute('href')).toBe('/');
  expect(api.get.mock.calls[0][1].params.exclude_categories).toBe("");
});
it("masque une catégorie par filtre API sans arrêter sa collecte et mémorise le choix", async () => {
  await act(async () => container.querySelector('input[type="checkbox"]').click());
  expect(api.get.mock.calls.at(-1)[1].params.exclude_categories).toBe("1499495158469758976");
  expect(JSON.parse(localStorage.getItem("iris.statistics.hiddenCategories"))).toEqual(["1499495158469758976"]);
  expect(container.textContent).toContain("La collecte conserve les données de toutes les catégories");
});
it("présente les erreurs et permet de réessayer", async () => {
  api.get.mockRejectedValueOnce(new Error("Erreur"));
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent.includes('Actualiser')).click());
  expect(container.querySelector('[role="alert"]').textContent).toContain("Erreur de collecte");
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent==='Réessayer').click());
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

it("transmet le regroupement et la désactivation de comparaison à tous les graphiques", async () => {
  const select=container.querySelector('[aria-label="Regrouper les messages"]');
  await act(async () => { select.value="month"; select.dispatchEvent(new Event("change",{bubbles:true})); });
  expect(api.get.mock.calls.at(-1)[1].params.granularity).toBe("month");
  await act(async () => container.querySelector('.ss-compare-toggle input').click());
  expect(api.get.mock.calls.at(-1)[1].params.compare).toBe(false);
});
it("permet de filtrer un membre depuis le tableau accessible du graphique", async () => {
  const card=[...container.querySelectorAll('.ss-chart-card')].find(el=>el.querySelector('h2').textContent==="Messages par membre");
  await act(async () => card.querySelector('button').click());
  expect(api.get.mock.calls.at(-1)[1].params.member_id).toBe("1");
});
