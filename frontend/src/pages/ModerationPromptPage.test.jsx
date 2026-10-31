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
