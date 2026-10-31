import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Module from './ResponsableToolsModule';
import StaffLinks from '../casework/CaseworkDashboardLinks';
jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>}),{virtual:true});
global.IS_REACT_ACT_ENVIRONMENT=true;
test('responsable tools keep all ten destinations in three named groups',async()=>{
 const host=document.createElement('div');const root=createRoot(host);
 try{
  await act(async()=>root.render(<Module/>));
  expect([...host.querySelectorAll('nav')].map(n=>n.getAttribute('aria-label'))).toEqual(['Discord et IA','Sécurité et archives','Pilotage']);
  const links=[...host.querySelectorAll('a')];
  expect(new Set(links.map(a=>a.getAttribute('href'))).size).toBe(10);
  expect(links.some(a=>a.getAttribute('href')==='/responsable/commandes-discord')).toBe(true);
  expect(links.some(a=>a.getAttribute('href')==='/responsable/archives-salons')).toBe(true);
 }finally{await act(async()=>root.unmount());}
});
test('staff cards include admission and anonymous history, with descriptions',async()=>{
 const host=document.createElement('div');const root=createRoot(host);
 try{
  await act(async()=>root.render(<StaffLinks isStaff/>));
  const links=[...host.querySelectorAll('a')];
  expect(links).toHaveLength(6);
  expect(links.every(a=>a.querySelector('strong')&&a.querySelector('small'))).toBe(true);
  expect(links.some(a=>a.getAttribute('href')==='/staff/verifications')).toBe(true);
  expect(links.some(a=>a.getAttribute('href')==='/staff/messages-anonymes')).toBe(true);
  await act(async()=>root.render(<StaffLinks/>));
  expect(host.querySelector('a')).toBeNull();
 }finally{await act(async()=>root.unmount());}
});
