import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ProjectRundown from './ProjectRundown';
import { api } from '../../api/client';
import { clockLabel, durationLabel, durationParts, durationMinutes, rundownText, rundownTimeline } from './rundownUtils';

jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>}),{virtual:true});
jest.mock('../../api/client',()=>({api:{get:jest.fn(),put:jest.fn()},getErrorMessage:()=> 'Erreur de déroulé'}));
jest.mock('sonner',()=>({toast:{success:jest.fn(),error:jest.fn()}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
const member={id:'m',username:'Alex',display_name:'Alex'};
const project={id:'p',title:'Soirée',status:'en_cours',start_date:'2026-10-27',members:[member]};
const plan={event_date:'2026-10-27',start_time:'23:30',updated_at:'2026-10-27T10:00:00Z',updated_by:member,items:[{id:'a',title:'Accueil',duration_minutes:10,speaker:member,notes:'Tester le micro'},{id:'b',title:'Jeux',duration_minutes:45,speaker:null,notes:''}]};
let root,container;
beforeEach(()=>{jest.clearAllMocks();container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
const click=async text=>{const b=[...container.querySelectorAll('button')].find(b=>b.textContent.includes(text));expect(b).toBeTruthy();await act(async()=>b.click());};
it('enchaîne les horaires, marque le lendemain et ne modifie pas la liste d’origine',()=>{
  const entries=rundownTimeline(plan.start_time,plan.items);
  expect(entries[0].start).toBe('23:30');expect(entries[0].end).toBe('23:40');expect(entries[1].end).toBe('00:25 · J+1');
  expect(plan.items[0].start).toBeUndefined();expect(durationLabel(85)).toBe('1 h 25 min');expect(clockLabel(1440)).toBe('00:00 · J+1');
  const text=rundownText({...project,rundown:plan});expect(text).toContain('heure de Paris');expect(text).toContain('Tester le micro');expect(text).toContain('Intervenant à attribuer');
});
it('prépare une trame, la réordonne et envoie les données du déroulé au serveur',async()=>{
  const saved=jest.fn();api.put.mockResolvedValue({data:{...project,rundown:plan}});
  await act(async()=>root.render(<ProjectRundown project={project} manager onSaved={saved}/>));
  await click('Préparer le déroulé');await click('Utiliser une trame simple');
  expect(container.querySelectorAll('.pj-sequence-edit')).toHaveLength(3);
  const select=container.querySelector('[aria-label="Intervenant de la séquence 1"]');
  await act(async()=>{select.value='m';select.dispatchEvent(new Event('change',{bubbles:true}));});
  await act(async()=>container.querySelector('[aria-label="Descendre la séquence 1"]').click());
  expect(container.querySelector('[aria-label="Nom de la séquence 1"]').value).toBe('Animation');
  await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.put).toHaveBeenCalledWith('/animateur/projects/p/rundown',expect.objectContaining({start_time:'20:00',expected_updated_at:null,items:expect.arrayContaining([expect.objectContaining({title:'Accueil',speaker_id:'m',duration_minutes:10})])}));expect(saved).toHaveBeenCalled();
});
it('pagine le déroulé pour éviter une longue page et le rend lisible aux membres',async()=>{
  const many={...plan,items:Array.from({length:15},(_,i)=>({...plan.items[0],id:`i-${i}`,title:`Séquence ${i+1}`}))};
  await act(async()=>root.render(<ProjectRundown project={{...project,rundown:many}} manager={false} onSaved={jest.fn()}/>));
  expect(container.querySelectorAll('.pj-rundown-timeline > li')).toHaveLength(8);
  await act(async()=>container.querySelector('[aria-label="Page suivante des séquences du déroulé"]').click());
  expect(container.querySelectorAll('.pj-rundown-timeline > li')).toHaveLength(7);
  expect(container.querySelector('h3').textContent).toContain('Séquence 9');expect(container.textContent).not.toContain('Modifier le déroulé');
});
it.each(['termine','archive'])('garde le projet %s en lecture seule',async status=>{
  await act(async()=>root.render(<ProjectRundown project={{...project,status,rundown:plan}} manager onSaved={jest.fn()}/>));
  expect(container.textContent).toContain('Accueil');expect(container.querySelector('form')).toBeNull();expect(container.textContent).not.toContain('Modifier le déroulé');
});
it('conserve le brouillon en cas de conflit et permet de recharger la version enregistrée',async()=>{
  function Wrapper(){const [value,setValue]=useState({...project,rundown:plan});return <ProjectRundown project={value} manager onSaved={setValue}/>;}
  api.put.mockRejectedValue({response:{status:409}});
  api.get.mockResolvedValue({data:{...project,rundown:{...plan,updated_at:'2026-10-27T11:00:00Z',items:[{...plan.items[0],title:'Version de l’équipe'}]}}});
  await act(async()=>root.render(<Wrapper/>));await click('Modifier le déroulé');
  await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(container.querySelector('form')).not.toBeNull();expect(container.textContent).toContain('Copiez vos modifications');
  await click('Recharger le déroulé');expect(container.querySelector('form')).toBeNull();expect(container.textContent).toContain('Version de l’équipe');
});

it('calcule les dates réelles sur plusieurs jours, fins de mois et années bissextiles',()=>{
  const items=[{id:'a',title:'Concours',duration_minutes:2*1440+195}];
  const timeline=rundownTimeline('23:30',items,'2026-12-30');
  expect(timeline[0].startDate).toBe('2026-12-30');expect(timeline[0].endDate).toBe('2027-01-02');expect(timeline[0].endClock).toBe('02:45');
  const leap=rundownTimeline('20:00',[{duration_minutes:2880}],'2028-02-28');
  expect(leap[0].endDate).toBe('2028-03-01');expect(leap[0].endClock).toBe('20:00');
  expect(durationLabel(3075)).toBe('2 j 3 h 15 min');expect(durationMinutes(durationParts(3075))).toBe(3075);
  expect(rundownText({...project,rundown:{...plan,event_date:'2026-12-30',items}})).toContain('2 janv. 2027');
});
it('enregistre une durée saisie en jours, heures et minutes et affiche les dates de chaque séquence',async()=>{
  const saved=jest.fn();api.put.mockResolvedValue({data:{...project,rundown:plan}});
  await act(async()=>root.render(<ProjectRundown project={{...project,rundown:plan}} manager onSaved={saved}/>));
  expect(container.querySelector('.pj-sequence-date').textContent).toContain('27 oct. 2026');await click('Modifier le déroulé');
  const fill=async(label,value)=>{const input=container.querySelector(`[aria-label="${label}"]`);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});};
  await fill('Jours de la séquence 1','2');await fill('Heures de la séquence 1','3');await fill('Minutes de la séquence 1','15');
  expect(container.textContent).not.toContain('24 h au maximum');
  const saveButton=[...container.querySelectorAll('button')].find(b=>b.textContent==='Enregistrer le déroulé');expect(saveButton.disabled).toBe(false);
  await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.put).toHaveBeenCalledWith('/animateur/projects/p/rundown',expect.objectContaining({items:expect.arrayContaining([expect.objectContaining({id:'a',duration_minutes:3075})])}));
  expect(api.put.mock.calls[0][1].items[0].duration_days).toBeUndefined();
});
