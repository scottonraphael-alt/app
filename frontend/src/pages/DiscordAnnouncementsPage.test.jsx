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

async function chooseFile(label,file){
  const input=container.querySelector(`input[aria-label="${label}"]`);
  await act(async()=>{Object.defineProperty(input,'files',{value:[file],configurable:true});input.dispatchEvent(new Event('change',{bubbles:true}));});
}
function mockUpload(content_type='image/png',filename='visuel.png'){
  const original=api.post.getMockImplementation();
  api.post.mockImplementation(async(url,body)=>url.endsWith('/assets')?{data:{id:'uploaded',original_filename:filename,discord_filename:'uploaded.png',content_type,size:123}}:original(url,body));
}
it('téléverse une image dans la galerie puis sauvegarde sa référence Iris',async()=>{
  mockUpload();await click('Galerie de médias');
  await value(container.querySelector('input[type="url"]'),'https://example.com/ancien.png');
  const file=new File(['image'],'visuel.png',{type:'image/png'});
  await chooseFile('Téléverser une image ou vidéo',file);
  expect(api.post.mock.calls.find(([url])=>url.endsWith('/assets'))[1].get('file')).toBe(file);
  expect(container.querySelector('.an-preview-gallery img').getAttribute('src')).toBe('/api/responsable/annonces/assets/uploaded/download');
  expect(container.querySelector('input[type="url"]')).toBeNull();
  await click('Enregistrer');
  expect(api.post.mock.calls.find(([url])=>url.endsWith('/drafts'))[1].document.groups[0].blocks[1].items[0]).toMatchObject({asset_id:'uploaded',url:''});
});
it('téléverse directement une vignette de section',async()=>{
  mockUpload();await click('Texte + accessoire');
  await chooseFile('Téléverser une image',new File(['image'],'visuel.png',{type:'image/png'}));
  expect(container.querySelector('.an-preview-section img').getAttribute('src')).toContain('/uploaded/download');
  await click('Enregistrer');
  expect(api.post.mock.calls.find(([url])=>url.endsWith('/drafts'))[1].document.groups[0].blocks[1].thumbnail.asset_id).toBe('uploaded');
});
it('joint un document directement depuis le bloc Fichier joint',async()=>{
  mockUpload('application/pdf','programme.pdf');await click('Fichier joint');
  await chooseFile('Téléverser un fichier joint',new File(['pdf'],'programme.pdf',{type:'application/pdf'}));
  expect(container.querySelector('.an-preview-file').textContent).toContain('programme.pdf');
  await click('Enregistrer');
  expect(api.post.mock.calls.find(([url])=>url.endsWith('/drafts'))[1].document.groups[0].blocks[1].file_asset_id).toBe('uploaded');
});
it('préserve le média précédent si le téléversement échoue',async()=>{
  await click('Galerie de médias');await value(container.querySelector('input[type="url"]'),'https://example.com/original.png');
  const original=api.post.getMockImplementation();api.post.mockImplementation(async(url,body)=>{if(url.endsWith('/assets'))throw new Error('Upload failed');return original(url,body);});
  await chooseFile('Téléverser une image ou vidéo',new File(['image'],'visuel.png',{type:'image/png'}));
  expect(container.querySelector('.an-preview-gallery img').getAttribute('src')).toBe('https://example.com/original.png');
  expect(toast.error).toHaveBeenCalledWith('Conflit de version');
});
it('refuse un fichier vide ou non affichable sans remplacer le média',async()=>{
  await click('Galerie de médias');
  await chooseFile('Téléverser une image ou vidéo',new File([],'vide.png',{type:'image/png'}));
  expect(api.post.mock.calls.filter(([url])=>url.endsWith('/assets'))).toHaveLength(0);
  expect(toast.error).toHaveBeenCalledWith('Le fichier est vide.');
  mockUpload('application/octet-stream','dessin.svg');
  await chooseFile('Téléverser une image ou vidéo',new File(['svg'],'dessin.svg',{type:'image/svg+xml'}));
  expect(container.querySelector('.an-preview-gallery img')).toBeNull();
  expect(toast.error.mock.calls.at(-1)[0]).toContain('bloc Fichier joint');
});
