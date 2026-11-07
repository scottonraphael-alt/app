import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Page from './ResolutionsPage';
import {api} from '../api/client';
jest.mock('../api/client',()=>({api:{get:jest.fn(),put:jest.fn()},getErrorMessage:()=> 'Erreur'}));
jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>}),{virtual:true});
jest.mock('../components/projects/ProjectUI',()=>({Modal:({title,children})=><div role="dialog"><h2>{title}</h2>{children}</div>}));
global.IS_REACT_ACT_ENVIRONMENT=true;
const row={_id:'123',number:'2026-25',title:'Une idée',explanation:'Texte complet',status:'approved',author_id:'456',positive:1,negative:0,votes:[{member_id:'789',choice:'yes',at:'2026-11-04T12:00:00Z'}],created_at:'2026-11-04T12:00:00Z'};
beforeEach(()=>jest.clearAllMocks());
test('archives show votes and Responsable numbering controls',async()=>{
 api.get.mockImplementation(url=>Promise.resolve({data:url.endsWith('/counter')?{year:2026,value:25,next_number:26}:{items:[row],total:1,can_manage_counter:true}}));
 api.put.mockResolvedValue({data:{year:2026,value:25,next_number:26}});
 const host=document.createElement('div'),root=createRoot(host);
 try{
 await act(async()=>root.render(<Page/>));
 expect(host.textContent).toContain('2026-25');
 expect(host.querySelector('#rz-next').value).toBe('26');
 const button=[...host.querySelectorAll('button')].find(b=>b.textContent==='Consulter');
 await act(async()=>button.click());
 expect(host.querySelector('[role="dialog"]').textContent).toContain('789');
 expect(host.querySelector('[role="dialog"]').textContent).toContain('Texte complet');
 const form=host.querySelector('.rz-counter form');
 await act(async()=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(api.put).toHaveBeenCalledWith('/resolutions/counter',{year:2026,expected_value:25,next_number:26});
 }finally{await act(async()=>root.unmount());}
});
test('non-Responsables cannot see counter controls and get an empty state',async()=>{
 api.get.mockResolvedValue({data:{items:[],total:0,can_manage_counter:false}});
 const host=document.createElement('div'),root=createRoot(host);
 try{
 await act(async()=>root.render(<Page/>));
 expect(host.querySelector('.rz-counter')).toBeNull();
 expect(host.textContent).toContain('Aucune résolution');
 expect(api.get).toHaveBeenCalledTimes(1);
 }finally{await act(async()=>root.unmount());}
});

test('ban archives distinguish decision, target and confirmed native execution',async()=>{
 const ban={...row,source_kind:'permanent_ban',target:{id:'710000000000000001',display_name:'Compte ciblé'},
 execution:{status:'uncertain'}};
 api.get.mockResolvedValue({data:{items:[ban],total:1,can_manage_counter:false}});
 const host=document.createElement('div'),root=createRoot(host);
 try{
 await act(async()=>root.render(<Page/>));
 expect(host.textContent).toContain('Bannissement définitif');
 expect(host.textContent).toContain('Compte ciblé');
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Consulter').click());
 const dialog=host.querySelector('[role="dialog"]');
 expect(dialog.textContent).toContain('710000000000000001');
 expect(dialog.textContent).toContain('aucun nouvel envoi automatique');
 expect(dialog.textContent).not.toContain('Bannissement exécuté et enregistré');
 }finally{await act(async()=>root.unmount());}
});
