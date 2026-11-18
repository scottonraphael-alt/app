import { act } from 'react';
import { createRoot } from 'react-dom/client';
import IconHint from './IconHint';
global.IS_REACT_ACT_ENVIRONMENT=true;
test('explains an icon on keyboard focus and dismisses the hint with Escape',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
 try{
  await act(async()=>root.render(<IconHint label="Fermer cette fenêtre (Échap)"><button aria-label="Fermer">×</button></IconHint>));
  const button=container.querySelector('button');
  await act(async()=>button.focus());
  const hint=document.querySelector('[role=tooltip]');
  expect(hint.textContent).toContain('Échap');expect(button.getAttribute('aria-describedby')).toBe(hint.id);
  await act(async()=>button.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
  expect(document.querySelector('[role=tooltip]')).toBeNull();expect(document.activeElement).toBe(button);
 }finally{await act(async()=>root.unmount());container.remove();}
});
