import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Page from './ModerationPromptPage';
import {api} from '../api/client';
jest.mock('react-router-dom',()=>({Link:({to,children})=><a href={to}>{children}</a>}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),put:jest.fn()},getErrorMessage:()=> 'Enregistrement refusé'}));
global.IS_REACT_ACT_ENVIRONMENT=true;
test('shows current moderation instructions and confirms a saved revision',async()=>{
 const data={revision:0,prompt:'Le prompt enregistré',rules:'Le règlement enregistré',sanctions:'Les sanctions enregistrées'};
 api.get.mockResolvedValue({data});api.put.mockResolvedValue({data:{...data,revision:1}});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<Page/>));
  expect([...host.querySelectorAll('textarea')].map(e=>e.value)).toEqual([data.prompt,data.rules,data.sanctions]);
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.put).toHaveBeenCalledWith('/responsable/moderation-prompt',data);
  expect(host.querySelector('[role="status"]').textContent).toContain('prochaines analyses');
 }finally{await act(async()=>root.unmount());host.remove();}
});

test.each([['Résumé des suivis','ticket_summary'],['Préavis des vérifications','verification'],['Copilote des suivis','copilot']])('edits %s independently',async(label,key)=>{
 const data={revision:2,prompt:'Consignes enregistrées pour cette analyse. '.repeat(5),default_prompt:'Consignes par défaut. '.repeat(8)};
 api.get.mockResolvedValue({data});api.put.mockResolvedValue({data:{...data,revision:3}});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<Page/>));
  await act(async()=>[...host.querySelectorAll('nav button')].find(b=>b.textContent===label).click());
  expect(api.get).toHaveBeenLastCalledWith('/responsable/moderation-prompt/analyses/'+key);
  expect(host.querySelectorAll('textarea')).toHaveLength(1);
  await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.put).toHaveBeenLastCalledWith('/responsable/moderation-prompt/analyses/'+key,{revision:2,prompt:data.prompt});
 }finally{await act(async()=>root.unmount());host.remove();}
});
