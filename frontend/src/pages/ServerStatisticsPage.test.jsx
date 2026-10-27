import { act } from "react";
import { createRoot } from "react-dom/client";
import ServerStatisticsPage from "./ServerStatisticsPage";
import { api } from "../api/client";

jest.mock("react-router-dom", () => ({ Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("@/Casier.css", () => ({}), { virtual: true });
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
  expect(container.textContent).toContain("Évolution des messages");
  expect(container.querySelectorAll('[data-testid="echarts-placeholder"]')).toHaveLength(1);
  expect(container.textContent).not.toContain("Messages par membre");
  expect(container.querySelector('a').getAttribute('href')).toBe('/');
  expect(api.get.mock.calls[0][1].params.exclude_categories).toBe("");
});
it("masque une catégorie par filtre API sans arrêter sa collecte et mémorise le choix", async () => {
  await act(async () => { container.querySelector(".ss-filter-drawer").open=true; container.querySelector(".ss-categories").open=true; container.querySelector('input[type="checkbox"]').click(); });
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
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find(el=>el.textContent==="Participants").click());
  const card=[...container.querySelectorAll('.ss-chart-card')].find(el=>el.querySelector('h2').textContent==="Messages par membre");
  await act(async () => card.querySelector('tbody .ss-data-button').click());
  expect(api.get.mock.calls.at(-1)[1].params.member_id).toBe("1");
});

it("charge les métriques des membres seulement après ouverture de leur onglet", async () => {
  api.get.mockResolvedValue({data:{...data,member_metrics:{
    status:"ready",population:10,active_present:3,active_ratio:30,joins:2,departures:1,growth:1,growth_rate:10,
    tracking_started_at:"2026-10-27T00:00:00Z",population_started_at:"2026-10-27T00:00:00Z",
    as_of:"2026-10-27T12:00:00Z",stale:false,daily:[],cohorts:[{day:"2026-10-01",members:2,checkpoints:{
      "7":{presence_percent:100,activity_percent:0,presence_eligible:1,present:1,activity_eligible:2,active:0},
      "30":{presence_percent:null,activity_percent:null,presence_eligible:0,present:0,activity_eligible:0,active:0},
    }}],activation:[],
    welcome:{eligible:0,welcomed:0,pending:2,unknown:0,distinct_welcomers:0,percent:null},
    renewal:null,regularity:[],regularity_distribution:[],reactivations:[],reactivated_members:0,
    activity_coverage:1,pending_observations:0,
  }}});
  expect(api.get.mock.calls[0][1].params.include_members).toBe(false);
  await act(async () => [...container.querySelectorAll('button')].find(button=>button.textContent==="Membres et fidélisation").click());
  expect(api.get.mock.calls.at(-1)[1].params.include_members).toBe(true);
  expect(container.textContent).toContain("Suivi des membres initialisé");
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find(el=>el.textContent==="Rétention").click());
  const retention=container.querySelector(".ss-chart-card");
  await act(async () => [...retention.querySelectorAll(".ss-representation button")].find(el=>el.textContent.includes("Tableau")).click());
  expect(container.textContent).toContain("Rétention des nouveaux membres");
  expect(container.textContent).toContain("100 % (1 / 1)");
  expect(container.textContent).toContain("0 % (0 / 2)");
  expect(container.textContent).toContain("En attente ou non disponible");
  expect(container.textContent).not.toContain("Salons les plus actifs");
});

it("ouvre les interactions avec un chargement dédié et masque les autres vues", async () => {
  api.get.mockResolvedValue({data:{...data,interaction_metrics:{
    mentions:3,replies:1,signals:4,unique_pairs:2,mutual_pairs:1,reciprocity:50,effective_contributors:1.5,active_contributors:2,coverage:1,
    diversity:[{id:"1",name:"Alex",peers:2,messages:3,outgoing_peers:2,incoming_peers:1,categories:1,mentions_sent:3,mentions_received:1,replies_sent:1}],
    participation:[],concentration:[{top:1,actual_members:1,messages:3,share:75}],cumulative_concentration:[{contributors:1,share:75,messages:3}],
    category_matrix:[],matrix_categories_shown:0,matrix_categories_total:0,
    restricted:{share:0,groups:[],signals:0,total_groups:0,max_group_size:5,min_signals:3},
    trend:{status:"insufficient",change:null,weeks:[]},quiet:{periods:[],total:0,min_samples:3,hour_threshold:3,day_threshold:20},
    responses:{available:false,bands:[],median_seconds:null},formula:{index:"Moyenne des trois dimensions"},
  }}});
  await act(async () => [...container.querySelectorAll('button')].find(button=>button.textContent==="Interactions et équilibre").click());
  const params=api.get.mock.calls.at(-1)[1].params;
  expect(params.include_interactions).toBe(true);
  expect(params.include_members).toBe(false);
  expect(container.textContent).toContain("Diversité des interlocuteurs");
  expect(container.textContent).not.toContain("Historique insuffisant");
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find(el=>el.textContent==="Tendances").click());
  expect(container.textContent).toContain("Historique insuffisant");
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find(el=>el.textContent==="Diversité").click());
  expect(container.textContent).not.toContain("Salons les plus actifs");
  const card=[...container.querySelectorAll('.ss-chart-card')].find(el=>el.querySelector('h2').textContent==="Diversité des interlocuteurs");
  await act(async () => card.querySelector('tbody .ss-data-button').click());
  expect(api.get.mock.calls.at(-1)[1].params.member_id).toBe("1");
});

it("ne monte qu’une analyse et permet le passage graphique / tableau sans nouvelle requête", async () => {
  const requests=api.get.mock.calls.length;
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find(el=>el.textContent==="Rythmes").click());
  expect(container.textContent).toContain("Heures de pointe");
  expect(container.querySelectorAll('[data-testid="echarts-placeholder"]')).toHaveLength(1);
  const card=container.querySelector('.ss-chart-card');
  await act(async () => [...card.querySelectorAll('.ss-representation button')].find(el=>el.textContent.includes('Tableau')).click());
  expect(container.querySelector('[data-testid="echarts-placeholder"]')).toBeNull();
  expect(card.querySelector('table')).not.toBeNull();
  expect(api.get.mock.calls.length).toBe(requests);
  expect(container.textContent).toContain("Comment lire ces données");
});
it("permet de choisir une analyse au clavier", async () => {
  const current=container.querySelector('[role="tab"][aria-selected="true"]');
  await act(async () => current.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})));
  expect(container.querySelector('[role="tab"][aria-selected="true"]').textContent).toBe('Rythmes');
  expect(document.activeElement.textContent).toBe('Rythmes');
});
it("masque réellement la navigation globale et la rétablit après avoir quitté la page", async () => {
  const fs=require('fs'); const path=require('path');
  const style=document.createElement('style');
  style.textContent=fs.readFileSync(path.join(__dirname,'../ServerStatistics.css'),'utf8');
  document.head.appendChild(style);
  const shell=document.createElement('div'); shell.className='app-shell';
  const sidebar=document.createElement('aside'); sidebar.className='sidebar'; shell.appendChild(sidebar);
  document.body.appendChild(shell);
  try {
    expect(window.getComputedStyle(sidebar).display).toBe('none');
    await act(async () => root.render(<div>Autre page</div>));
    expect(document.body.classList.contains('statistics-no-nav')).toBe(false);
    expect(window.getComputedStyle(sidebar).display).not.toBe('none');
  } finally { shell.remove(); style.remove(); }
});
