import {act} from 'react';
import {createRoot} from 'react-dom/client';
import WorkflowSettingsPage from './WorkflowSettingsPage';
import {api} from '../api/client';
jest.mock('react-router-dom',()=>({Link:({to,children})=><a href={to}>{children}</a>}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn(),put:jest.fn(),post:jest.fn()},getErrorMessage:()=> 'Erreur'}));
jest.mock('../components/casework/WorkflowRequests',()=>()=>null);
global.IS_REACT_ACT_ENVIRONMENT=true;
test('shows the exact blocked form destination while distinguishing welcome permissions',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
 api.get.mockResolvedValue({data:{revision:0,ids:{},gifs:[],admission_rules:'',roles:[],channels:[],native_enabled:true,
 verification_delivery:{forms:{ok:false,message:'Visiteurs (22) peut lire formulaires (1425589415165558825).'},welcome:{ok:true,message:'Salon accueil (1081957994125860905) accessible.'}}}});
 try{
  await act(async()=>root.render(<WorkflowSettingsPage/>));
  expect(container.querySelector('[role="alert"]').textContent).toContain('Visiteurs (22)');
  expect(container.textContent).toContain('Bienvenue après validation : permissions vérifiées');
  expect(container.textContent).toContain('1425589415165558825');
  expect(api.post).not.toHaveBeenCalled();expect(api.put).not.toHaveBeenCalled();
 }finally{await act(async()=>root.unmount());container.remove();}
});
