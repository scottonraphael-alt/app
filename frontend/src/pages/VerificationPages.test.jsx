import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { VerificationListPage, VerificationDetailPage } from './VerificationPages';
import { api } from '../api/client';
jest.mock('react-router-dom',()=>({Link:({to,children,...rest})=><a href={to} {...rest}>{children}</a>,useParams:()=>({memberId:'500000000000000001'})}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),post:jest.fn(),delete:jest.fn(),patch:jest.fn()},getErrorMessage:()=> 'Le dossier a changé.'}));
jest.mock('../components/projects/ProjectUI',()=>({Modal:({title,children,onClose})=><div role="dialog"><h2>{title}</h2>{children}<button onClick={onClose}>Fermer</button></div>}));
global.IS_REACT_ACT_ENVIRONMENT=true;
const row={member_id:'500000000000000001',member:{display_name:'Alex'},status:'waiting',active:true,revision:1,claimed_by:null,training:false,form_count:1,last_form_at:null,
forms:[{id:'form-1',answers:{name:'Alex',age:'18-25',reason:'Présentation personnelle',psychiatry:'Mon avis sur la psychiatrie',rules:true},status:'waiting',submitted_at:null}],jobs:[],events:[]};
let container,root;
const button=text=>[...container.querySelectorAll('button')].find(el=>el.textContent.trim()===text);
beforeEach(()=>{jest.clearAllMocks();container=document.createElement('div');document.body.append(container);root=createRoot(container);Object.defineProperty(global,'crypto',{configurable:true,value:{randomUUID:()=> 'test-uuid-0001'}});});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
const render=async element=>{await act(async()=>root.render(element));};
const click=async element=>{await act(async()=>element.click());};
test('pending/archive switches query and keeps a compact member list',async()=>{
 api.get.mockResolvedValue({data:{items:[row],total:1}});await render(<VerificationListPage/>);
 expect(container.querySelector('table').textContent).toContain('Alex');expect(container.textContent).toContain('Date non connue');
 await click(button('Archives'));expect(api.get).toHaveBeenLastCalledWith('/staff/verifications',{params:{archive:true,offset:0,limit:25}});
 expect(document.body.classList.contains('casier-no-nav')).toBe(true);
});
test('no action sent before explicit confirmation; retry preserves idempotency key',async()=>{
 api.get.mockResolvedValue({data:row});api.post.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({data:{...row,status:'claimed',revision:2}});
 await render(<VerificationDetailPage/>);
 await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(api.post).not.toHaveBeenCalled();expect(container.querySelector('[role=dialog]')).toBeTruthy();
 await click(button('Confirmer'));expect(container.textContent).toContain('Le dossier a changé.');
 await click(button('Confirmer'));expect(api.post).toHaveBeenCalledTimes(2);expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]);
 expect(container.querySelector('[role=dialog]')).toBeNull();
});
test('responsible deletion requires the exact form identifier',async()=>{
 api.get.mockResolvedValue({data:row});await render(<VerificationDetailPage responsable/>);
 await click(button('Supprimer cette tentative'));const dialog=container.querySelector('[role=dialog]');
 expect(dialog.textContent).toContain('Les rôles, sanctions, tickets et archives Discord ne seront pas supprimés.');
 expect(button('Confirmer').disabled).toBe(true);expect(api.delete).not.toHaveBeenCalled();
});
test('pending effects prevent another decision and show readable step labels',async()=>{
 api.get.mockResolvedValue({data:{...row,status:'processing',jobs:[{id:'job-1',action:'approve',status:'pending',steps:[{name:'member_access',status:'pending'}]}]}});
 await render(<VerificationDetailPage/>);expect(container.querySelector('form')).toBeNull();
 expect(container.textContent).toContain('Attribution des accès : En attente');expect(container.textContent).not.toContain('member_access');
});
