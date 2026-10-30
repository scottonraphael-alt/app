import {act,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Editor from './WorkflowPanelEditor';
jest.mock("react-router-dom",()=>({Link:({children,to})=><a href={to}>{children}</a>}),{virtual:true});
global.IS_REACT_ACT_ENVIRONMENT=true;
test('edits a panel without submitting settings and preserves other panels',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const save=jest.fn();let latest;
 function Harness(){const [panels,setPanels]=useState({'public:verification':{color:'#78618c',blocks:[]}});latest=panels;
 return <form onSubmit={e=>{e.preventDefault();save();}}><Editor value={panels} onChange={setPanels} catalogue={{roles:[],channels:[]}}/></form>;}
 try{
  await act(async()=>root.render(<Harness/>));
  const add=[...host.querySelectorAll('button')].find(b=>b.textContent==='+ Texte');
  await act(async()=>add.click());
  expect(latest['public:support'].blocks).toHaveLength(1);
  expect(latest['public:verification']).toBeDefined();
  const bold=[...host.querySelectorAll('button')].find(b=>b.textContent==='Gras');
  expect(bold.type).toBe('button');
  expect(save).not.toHaveBeenCalled();
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Rétablir le contenu d’origine').click());
  expect(latest['public:support']).toBeUndefined();
  expect(latest['public:verification']).toBeDefined();
 }finally{await act(async()=>root.unmount());host.remove();}
});
