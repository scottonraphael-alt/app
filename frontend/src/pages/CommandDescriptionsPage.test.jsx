import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Page from './CommandDescriptionsPage';
import {api} from '../api/client';
jest.mock('react-router-dom',()=>({Link:({to,children})=><a href={to}>{children}</a>}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),put:jest.fn()},getErrorMessage:()=> 'Erreur'}));
global.IS_REACT_ACT_ENVIRONMENT=true;
test('lists command and parameter descriptions with their original-text controls',async()=>{
 api.get.mockResolvedValue({data:{revision:0,overrides:{},sync_errors:{},items:[
 {path:'panel/moderation',kind:'commande',description:'Ouvrir le panneau',default:'Ouvrir le panneau'},
 {path:'convocation/membre',kind:'paramètre',description:'Membre concerné',default:'Membre concerné'}]}});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<Page/>));
  expect(host.textContent).toContain('/panel moderation');
  expect(host.textContent).toContain('/convocation membre');
  expect([...host.querySelectorAll('button')].filter(b=>b.textContent==='Texte d’origine')).toHaveLength(2);
  expect([...host.querySelectorAll('input')].filter(i=>i.required).every(i=>i.maxLength===100)).toBe(true);
 }finally{await act(async()=>root.unmount());host.remove();}
});
