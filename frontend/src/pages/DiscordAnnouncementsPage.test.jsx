import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DiscordAnnouncementsPage from './DiscordAnnouncementsPage';
import { api } from '../api/client';
import { toast } from 'sonner';

jest.mock('react-router-dom',()=>({Link:({children,to,...props})=><a href={to} {...props}>{children}</a>,useSearchParams:()=>[new URLSearchParams(),jest.fn()]}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),post:jest.fn(),put:jest.fn(),delete:jest.fn(),defaults:{baseURL:'/api'}},getErrorMessage:error=>error?.response?.data?.detail || 'Conflit de version'}));
jest.mock('sonner',()=>({toast:{success:jest.fn(),error:jest.fn()}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,container;
const channel='700000000000000001',role='300000000000000001';
const getButton=(text,scope=container)=>[...scope.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const click=async text=>act(async()=>getButton(text).click());
async function value(el,text){await act(async()=>{const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,text);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));});}
const publications=()=>api.post.mock.calls.filter(([url])=>url.endsWith('/publish'));
beforeEach(async()=>{
  jest.clearAllMocks();localStorage.clear();window.confirm=jest.fn(()=>true);
  api.get.mockImplementation(async url=>({data:url.endsWith('/catalogue')?{guild_id:'100000000000000001',channels:[{id:channel,name:'annonces'}],roles:[{id:role,name:'Helper'}]}:{items:[],total:0,page:1}}));
  api.post.mockImplementation(async(url,body)=>({data:url.endsWith('/drafts')?{...body,id:'saved',revision:1}:url.endsWith('/publish')?{id:'sent',status:'sent'}:{}}));
  api.put.mockImplementation(async(url,body)=>({data:{...body,id:'saved',revision:2}}));
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
  await act(async()=>root.render(<DiscordAnnouncementsPage helper={{id:'responsable'}}/>));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
async function destination(){await click('Distribution');await value(container.querySelector('.an-fields select'),channel);}

it('propose les blocs et un aperçu, avec le retour au tableau de bord',async()=>{
  expect(document.body.classList.contains('announcements-no-nav')).toBe(true);
  expect(container.querySelector('.cz-home').getAttribute('href')).toBe('/');
  expect(container.querySelector('.an-discord-preview').textContent).toContain('Une nouvelle annonce');
  await click('Galerie de médias');
  expect(container.querySelectorAll('.an-block-outline li')).toHaveLength(2);
  expect(container.querySelector('.an-validation').textContent).toContain('URL HTTPS');
  expect(container.querySelectorAll('.an-inspector')).toHaveLength(1);
  await act(async()=>container.querySelector('[aria-label="Retirer le bloc 2"]').click());
  expect(container.querySelector('.an-validation')).toBeNull();
});

it('enregistre la version puis attend la confirmation explicite avant tout envoi',async()=>{
  await destination();await click('Publier');
  expect(publications()).toHaveLength(0);
  const dialog=document.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain('version 1');expect(dialog.textContent).toContain('#annonces');
  expect(dialog.textContent).toContain('ANNONCES DISCORD');
  const saved=api.post.mock.calls.find(([url])=>url.endsWith('/drafts'))[1];
  expect(saved.document.mentions).toEqual({roles:[],users:[],everyone:false});
  await act(async()=>getButton('Envoyer sur Discord',dialog).click());
  expect(publications()).toHaveLength(1);
  expect(publications()[0][1]).toMatchObject({expected_revision:1,mode:'create',target_id:null,schedule_local:null});
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it('permet les mentions ciblées et la programmation en heure de Paris',async()=>{
  await destination();
  const helper=[...container.querySelectorAll('.an-role-list label')].find(el=>el.textContent==='@Helper');
  await act(async()=>helper.querySelector('input').click());
  await click('Publier');
  const dialog=document.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain('1 rôle(s) · 0 utilisateur(s)');
  await act(async()=>dialog.querySelector('input[type="checkbox"]').click());
  await value(dialog.querySelector('input[type="datetime-local"]'),'2027-04-01T12:00');
  await act(async()=>getButton('Programmer cette annonce',dialog).click());
  expect(publications()[0][1].schedule_local).toBe('2027-04-01T12:00');
  expect(api.post.mock.calls.find(([url])=>url.endsWith('/drafts'))[1].document.mentions.roles).toEqual([role]);
});

it('conserve le brouillon et ne publie pas si l’enregistrement échoue',async()=>{
  await destination();api.post.mockImplementation(async(url)=>{if(url.endsWith('/drafts'))throw new Error('Conflict');return {data:{}};});
  await click('Publier');
  expect(document.querySelector('[role="dialog"]')).toBeNull();expect(publications()).toHaveLength(0);
  expect(toast.error).toHaveBeenCalledWith('Conflit de version');
  expect(container.textContent).toContain('Modifications non enregistrées');
});

it('annule la confirmation sans envoi et garde les mentions générales désactivées',async()=>{
  await destination();await click('Publier');
  await act(async()=>getButton('Revenir au brouillon',document.querySelector('[role="dialog"]')).click());
  expect(publications()).toHaveLength(0);
  await click('Distribution');
  expect([...container.querySelectorAll('label')].find(el=>el.textContent==='Autoriser @everyone et @here').querySelector('input').checked).toBe(false);
});

it('présente les erreurs de validation API sans rendre leurs objets comme du texte',async()=>{
  api.post.mockImplementation(async url=>{if(url.endsWith('/drafts'))throw {response:{data:{detail:[{msg:'String too short'}]}}};return {data:{}};});
  await click('Enregistrer');
  expect(toast.error).toHaveBeenCalledWith('Les données ne sont pas valides. Vérifiez les champs et les limites du composeur.');
});
