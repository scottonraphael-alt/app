import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Page from './AnonymousMessagesPage';
import {api} from '../api/client';
jest.mock('react-router-dom',()=>({Link:({to,children})=><a href={to}>{children}</a>}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),post:jest.fn()},getErrorMessage:()=> 'Accès refusé'}));
jest.mock('../components/projects/ProjectUI',()=>({Modal:({title,children})=><div role="dialog"><h2>{title}</h2>{children}</div>}));
global.IS_REACT_ACT_ENVIRONMENT=true;
const row={_id:'guild:message',alias:'ANO-AB12-CD',text:'Un message personnel à lire.',status:'pending',created_at:'2026-10-31T00:00:00Z'};
test.each([false,true])('history reveals only after an explicit authorized action (%s)',async canReveal=>{
 api.get.mockResolvedValue({data:{items:[row],total:1,can_reveal:canReveal}});
 api.post.mockResolvedValue({data:{member_id:'123456789012345678',alias:row.alias}});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<Page/>));
  expect(host.textContent).toContain(row.alias);
  expect(host.textContent).not.toContain('123456789012345678');
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Lire').click());
  const reveal=[...host.querySelectorAll('button')].find(b=>b.textContent.includes('Révéler l’auteur'));
  expect(!!reveal).toBe(canReveal);
  if(canReveal){
   await act(async()=>reveal.click());
   expect(host.querySelector('[role="dialog"]').textContent).toContain('123456789012345678');
  }
 }finally{await act(async()=>root.unmount());host.remove();}
});
