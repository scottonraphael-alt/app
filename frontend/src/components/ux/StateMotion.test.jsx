import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ChangeCue from './ChangeCue';
import StableLabel from './StableLabel';
import ScrollEdges, { scrollEdges } from './ScrollEdges';
import Disclosure from './Disclosure';
import { MOTION_EVENT } from '../../hooks/useMotionPreference';
jest.mock('react-router-dom',()=>({Link:({children,...props})=><a {...props}>{children}</a>}),{virtual:true});
jest.mock('../projects/projectAudit',()=>({useProjectAudit:()=>{}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
let container,root;
const originalAnimate=Element.prototype.animate;
beforeEach(()=>{container=document.createElement('div');document.body.append(container);root=createRoot(container);delete document.documentElement.dataset.motion;});
afterEach(()=>{act(()=>root.unmount());container.remove();Element.prototype.animate=originalAnimate;delete document.documentElement.dataset.motion;});
test('only highlights changed values and cancels the effect when reduced motion is enabled',()=>{
 const cancel=jest.fn();Element.prototype.animate=jest.fn(()=>({cancel}));
 act(()=>root.render(<ChangeCue value="open">Ouvert</ChangeCue>));expect(Element.prototype.animate).not.toHaveBeenCalled();
 act(()=>root.render(<ChangeCue value="archived">Archivé</ChangeCue>));expect(Element.prototype.animate).toHaveBeenCalledTimes(1);
 act(()=>{document.documentElement.dataset.motion='reduced';window.dispatchEvent(new Event(MOTION_EVENT));});expect(cancel).toHaveBeenCalled();
 act(()=>root.render(<ChangeCue value="open">Ouvert</ChangeCue>));expect(Element.prototype.animate).toHaveBeenCalledTimes(1);
});
test('reserves label variants without duplicating real button text or its accessible content',()=>{
 act(()=>root.render(<button><StableLabel variants={['Enregistrer','Enregistrement…','Enregistré']}>Enregistrer</StableLabel></button>));
 expect(container.querySelector('button').textContent).toBe('Enregistrer');
 expect([...container.querySelectorAll('.iris-label-reserve')].every(el=>el.getAttribute('aria-hidden')==='true')).toBe(true);
 act(()=>root.render(<button><StableLabel variants={['Enregistrer','Enregistrement…','Enregistré']}>Enregistrement…</StableLabel></button>));
 expect(container.querySelector('button').textContent).toBe('Enregistrement…');
});
test('scroll cues reflect overflow, disappear at the end and clamp overscroll',()=>{
 const node={scrollWidth:900,clientWidth:300,scrollHeight:700,clientHeight:200,scrollLeft:0,scrollTop:0};
 expect(scrollEdges(node)).toEqual({left:false,right:true,top:false,bottom:true});
 expect(scrollEdges({...node,scrollLeft:600,scrollTop:500})).toEqual({left:true,right:false,top:true,bottom:false});
 expect(scrollEdges({...node,scrollLeft:-20,scrollTop:-10})).toEqual({left:false,right:true,top:false,bottom:true});
 act(()=>root.render(<ScrollEdges className="test-scroll" label="Tableau"><table><tbody><tr><td>Une donnée</td></tr></tbody></table></ScrollEdges>));
 const viewport=container.querySelector('.test-scroll');
 for(const [key,value] of Object.entries(node))Object.defineProperty(viewport,key,{configurable:true,writable:true,value});
 act(()=>window.dispatchEvent(new Event('resize')));
 expect(container.querySelector('.iris-scroll-edge--right').dataset.visible).toBe('true');expect(viewport.tabIndex).toBe(0);
 viewport.scrollLeft=600;act(()=>viewport.dispatchEvent(new Event('scroll')));
 expect(container.querySelector('.iris-scroll-edge--right').hasAttribute('data-visible')).toBe(false);
 expect(container.querySelector('.iris-scroll-edge--left').dataset.visible).toBe('true');
});
test('disclosure exposes its state and preserves parent-owned draft text across reopening',()=>{
 function Fixture(){const[note,setNote]=useState('Texte conservé');return <Disclosure title="La suite"><input aria-label="Note" value={note} onChange={e=>setNote(e.target.value)}/></Disclosure>;}
 act(()=>root.render(<Fixture/>));const trigger=container.querySelector('button');
 expect(trigger.getAttribute('aria-expanded')).toBe('false');
 act(()=>trigger.click());expect(trigger.getAttribute('aria-expanded')).toBe('true');expect(container.querySelector('input').value).toBe('Texte conservé');
 act(()=>trigger.click());expect(trigger.getAttribute('aria-expanded')).toBe('false');
 act(()=>trigger.click());expect(container.querySelector('input').value).toBe('Texte conservé');
});

test('dialog dismissal points gently toward the opener and keeps the existing close delay',async()=>{
 const {Modal}=require('../projects/ProjectUI');
 const originalRect=Element.prototype.getBoundingClientRect;
 const opener=document.createElement('button');document.body.append(opener);opener.focus();
 Element.prototype.getBoundingClientRect=function(){return this===opener ? {left:40,top:40,width:80,height:40} : this.classList?.contains('pj-modal') ? {left:200,top:200,width:600,height:400} : originalRect.call(this);};
 const close=jest.fn();
 try{
  await act(async()=>root.render(<Modal title="Un réglage" onClose={close}>Contenu</Modal>));
  await act(async()=>document.querySelector('[aria-label="Fermer"]').click());
  const modal=document.querySelector('.pj-modal');
  expect(modal.style.getPropertyValue('--iris-return-x')).toBe('-63px');
  expect(modal.style.getPropertyValue('--iris-return-y')).toBe('-48px');
  expect(close).not.toHaveBeenCalled();
  await act(async()=>new Promise(resolve=>setTimeout(resolve,180)));expect(close).toHaveBeenCalledTimes(1);
 }finally{Element.prototype.getBoundingClientRect=originalRect;opener.remove();}
});
