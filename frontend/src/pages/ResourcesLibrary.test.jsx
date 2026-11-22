import {act} from 'react';
import {createRoot} from 'react-dom/client';
import ResourcesPage from './ResourcesPage';
import {api} from '../api/client';

jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>}),{virtual:true});
jest.mock('../api/client',()=>({api:{get:jest.fn()},getErrorMessage:()=> 'Erreur'}));
jest.mock('sonner',()=>({toast:{error:jest.fn()}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,container;
beforeEach(()=>{
 container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
 api.get.mockResolvedValue({data:{resources:[{id:'guide',title:'Guide de l’équipe',category:'Équipe',original_filename:'guide.pdf',content_type:'application/pdf',size:1200}]}});
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();jest.clearAllMocks()});

test('met en avant un document réel sans exposer les outils de dépôt aux non-admins',async()=>{
 await act(async()=>root.render(<ResourcesPage/>));
 expect(container.querySelector('.rl-featured h2').textContent).toBe('Guide de l’équipe');
 expect(container.querySelector('[data-testid="resource-card-guide"]')).not.toBeNull();
 expect(container.querySelector('.rl-upload-disclosure')).toBeNull();
 const category=[...container.querySelectorAll('.rl-filters button')].find(b=>b.textContent==='Équipe');
 await act(async()=>category.click());
 expect(container.querySelector('.rl-featured')).toBeNull();
 expect(container.querySelector('[data-testid="resource-card-guide"]')).not.toBeNull();
});

test('conserve le formulaire de dépôt dans une section native dépliable',async()=>{
 await act(async()=>root.render(<ResourcesPage isAdmin/>));
 const section=container.querySelector('.rl-upload-disclosure');
 expect(section.open).toBe(false);
 expect(section.querySelector('summary').textContent).toContain('Partager une ressource');
 section.open=true;
 expect(section.querySelector('input[type=file]')).not.toBeNull();
 expect(section.querySelector('[data-testid="resource-upload-form"]')).not.toBeNull();
});
