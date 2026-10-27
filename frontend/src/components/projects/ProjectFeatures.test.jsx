import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ProjectForm from './ProjectForm';
import ProjectReview from './ProjectReview';
import ProjectTaskDialog, { TaskForm } from './ProjectTaskDialog';
import ProjectTemplateSave from './ProjectTemplateSave';
import { api } from '../../api/client';

jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>}),{virtual:true});
jest.mock('../../api/client',()=>({api:{get:jest.fn(),post:jest.fn(),patch:jest.fn(),put:jest.fn(),delete:jest.fn(),defaults:{baseURL:'/api'}},getErrorMessage:()=> 'Erreur de projet'}));
jest.mock('../SummaryReader',()=>({content})=><div>{content}</div>);
jest.mock('../TiptapSummaryEditor',()=>({value,onChange})=><textarea aria-label="Rendu" value={value} onChange={e=>onChange(e.target.value)}/>);
jest.mock('sonner',()=>({toast:{success:jest.fn(),error:jest.fn()}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
const member={id:'owner',username:'Alex',display_name:'Alex'};
const project={id:'p',title:'Soirée jeux',description:'Une belle soirée',start_date:'2026-10-27',end_date:'2026-11-01',status:'en_cours',created_by:member,members:[member],tags:['Jeux']};
const task={id:'t',title:'Préparer',status:'a_faire',assignee:member,due_date:'2026-11-01',updated_at:'2026-10-27T10:00:00Z',checklist:[{id:'step',title:'Tester le matériel',done:false}]};
const templates=[{id:'builtin-games',name:'Soirée jeux',description:'Un cadre prêt à adapter',tags:['Jeux'],builtin:true,tasks:[{title:'Choisir les jeux'}]}];
let root,container;
beforeEach(()=>{jest.clearAllMocks();api.get.mockResolvedValue({data:templates});api.post.mockResolvedValue({data:{...project,template_id:'builtin-games'}});container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
const click=async text=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes(text));expect(b).toBeTruthy();await act(async()=>b.click());};
const field=label=>[...document.querySelectorAll('label')].find(l=>l.querySelector(':scope > span')?.textContent===label)?.querySelector('input,textarea,select');
const fill=async(el,value)=>{expect(el).toBeTruthy();const prototype=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;await act(async()=>{Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));});};
const submit=async()=>{await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));};
it('prévisualise un modèle et le transmet lors de la création du projet',async()=>{
  const saved=jest.fn();await act(async()=>root.render(<ProjectForm onClose={jest.fn()} onSaved={saved}/>));
  expect(api.get).toHaveBeenCalledWith('/animateur/projects/workspace/templates');
  const select=field('Partir d’un modèle · facultatif');await act(async()=>{select.value='builtin-games';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(document.body.textContent).toContain('Choisir les jeux');
  expect(field('Nom du projet').value).toBe('Soirée jeux');
  await fill(field('Nom du projet'),'Soirée du samedi');await submit();
  expect(api.post).toHaveBeenCalledWith('/animateur/projects',expect.objectContaining({template_id:'builtin-games',title:'Soirée du samedi',tags:['Jeux']}));
  expect(saved).toHaveBeenCalled();
});
it('laisse créer un projet libre si le catalogue des modèles est indisponible',async()=>{
  api.get.mockRejectedValue(new Error('offline'));
  await act(async()=>root.render(<ProjectForm onClose={jest.fn()} onSaved={jest.fn()}/>));
  expect(document.body.textContent).toContain('Vous pouvez créer un projet libre');
  await fill(field('Nom du projet'),'Libre');await submit();
  expect(api.post).toHaveBeenCalledWith('/animateur/projects',expect.objectContaining({template_id:null,title:'Libre'}));
});
it('enregistre un projet existant comme modèle partagé sans modifier le projet',async()=>{
  const close=jest.fn();await act(async()=>root.render(<ProjectTemplateSave project={project} onClose={close}/>));
  expect(document.body.textContent).toContain('toute l’équipe d’animation');
  await fill(field('Nom du modèle partagé'),'Notre soirée');await submit();
  expect(api.post).toHaveBeenCalledWith('/animateur/projects/p/template',{name:'Notre soirée'});expect(close).toHaveBeenCalled();
});
it('ajoute des étapes à une tâche depuis son formulaire',async()=>{
  await act(async()=>root.render(<TaskForm project={project} onClose={jest.fn()} onSaved={jest.fn()}/>));
  await fill(field('Nom de la tâche'),'Préparer le matériel');
  await fill(document.querySelector('[aria-label="Nouvelle étape de la checklist"]'),'Tester le micro');await click('Ajouter l’étape');
  expect(document.querySelector('[aria-label="Étape 1"]').value).toBe('Tester le micro');await submit();
  expect(api.post).toHaveBeenCalledWith('/animateur/projects/p/tasks',expect.objectContaining({checklist:[expect.objectContaining({title:'Tester le micro',done:false,id:expect.any(String)})]}));
});
it('coche une étape avec la version du serveur et débloque l’envoi du rendu',async()=>{
  function Wrapper(){const [value,setValue]=useState(task);return <ProjectTaskDialog task={value} helper={member} manager={false} writable members={[member]} onSaved={setValue} onClose={jest.fn()}/>;}
  api.patch.mockResolvedValue({data:{...task,updated_at:'2026-10-27T10:01:00Z',checklist:[{...task.checklist[0],done:true}]}});
  await act(async()=>root.render(<Wrapper/>));await click('Préparer mon rendu');
  expect([...document.querySelectorAll('button')].find(b=>b.textContent==='Envoyer pour validation').disabled).toBe(true);
  await act(async()=>document.querySelector('input[type="checkbox"]').click());
  expect(api.patch).toHaveBeenCalledWith('/animateur/tasks/t/checklist/step',{done:true,expected_updated_at:task.updated_at});
  expect(document.querySelector('input[type="checkbox"]').checked).toBe(true);
  expect([...document.querySelectorAll('button')].find(b=>b.textContent==='Envoyer pour validation').disabled).toBe(false);
});
it('permet de compléter le bilan d’un projet terminé et préserve une participation de zéro',async()=>{
  const saved=jest.fn();api.put.mockResolvedValue({data:{...project,status:'termine',review:{attendance:0}}});
  await act(async()=>root.render(<ProjectReview project={{...project,status:'termine'}} manager onSaved={saved}/>));await click('Rédiger le bilan');
  await fill(field('Nombre de participants · facultatif'),'0');await fill(field('Ce qui a bien fonctionné'),'Une équipe à l’écoute');await submit();
  expect(api.put).toHaveBeenCalledWith('/animateur/projects/p/review',expect.objectContaining({attendance:0,successes:'Une équipe à l’écoute',expected_updated_at:null}));expect(saved).toHaveBeenCalled();
});
it('garde un bilan archivé en lecture seule',async()=>{
  await act(async()=>root.render(<ProjectReview project={{...project,status:'archive',review:{attendance:15,successes:'Une réussite',updated_at:'2026-10-27T10:00:00Z',updated_by:member}}} manager onSaved={jest.fn()}/>));
  expect(document.body.textContent).toContain('Une réussite');expect(document.querySelector('form')).toBeNull();expect(document.body.textContent).not.toContain('Modifier le bilan');
});
