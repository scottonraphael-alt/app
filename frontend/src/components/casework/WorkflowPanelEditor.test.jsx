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

test('convocation preset renders a heading with a right thumbnail',async()=>{
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);let latest;
 function Harness(){const [panels,setPanels]=useState({});latest=panels;return <Editor value={panels} onChange={setPanels} catalogue={{roles:[],channels:[]}}/>;}
 try{
  await act(async()=>root.render(<Harness/>));
  await act(async()=>{const select=host.querySelector('select');select.value='room:summons';select.dispatchEvent(new Event('change',{bubbles:true}));});
  await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Utiliser le modèle Convocation avec vignette').click());
  expect(latest['room:summons'].replace_heading).toBe(true);
  expect(latest['room:summons'].blocks[0].kind).toBe('section');
  expect(latest['room:summons'].blocks[0].text).toContain('{membre}');
  expect(host.querySelector('.wf-section-preview').textContent).toContain('Convocation de @Membre');
  expect(host.querySelector('.wf-thumbnail-empty')).not.toBeNull();
 }finally{await act(async()=>root.unmount());host.remove();}
});
