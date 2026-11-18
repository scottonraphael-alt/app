import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Field } from '../projects/ProjectUI';
jest.mock('react-router-dom',()=>({Link:({children,...props})=><a {...props}>{children}</a>}),{virtual:true});
jest.mock('../projects/projectAudit',()=>({useProjectAudit:()=>{}}));
global.IS_REACT_ACT_ENVIRONMENT=true;
let container,root;
beforeEach(()=>{container=document.createElement('div');document.body.append(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
test('links required errors and hints to the field, preserves existing callbacks and clears corrected errors',()=>{
 const change=jest.fn(),invalid=jest.fn();
 act(()=>root.render(<Field label="Votre nom" hint="Un nom court suffit."><input required aria-describedby="existing-note" onChange={change} onInvalid={invalid}/></Field>));
 const input=container.querySelector('input');act(()=>input.dispatchEvent(new Event('invalid',{bubbles:false})));
 expect(invalid).toHaveBeenCalled();expect(input.getAttribute('aria-invalid')).toBe('true');
 const descriptions=input.getAttribute('aria-describedby').split(' ');
 expect(descriptions).toContain('existing-note');expect(descriptions).toContain(container.querySelector('[role=alert]').id);
 expect(descriptions).toContain(container.querySelector('.iris-field-hint').id);
 act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Camille');input.dispatchEvent(new Event('input',{bubbles:true}));});
 expect(change).toHaveBeenCalled();expect(container.querySelector('[role=alert]')).toBeNull();expect(input.hasAttribute('aria-invalid')).toBe(false);
 expect(document.getElementById(input.getAttribute('aria-labelledby')).textContent).toBe('Votre nom');
});
test('validates a filled email on blur without showing an error before interaction',()=>{
 act(()=>root.render(<Field label="Courriel"><input type="email" defaultValue="invalide"/></Field>));
 expect(container.querySelector('[role=alert]')).toBeNull();
 act(()=>container.querySelector('input').dispatchEvent(new FocusEvent('focusout',{bubbles:true})));
 expect(container.querySelector('[role=alert]').textContent).toContain('Vérifiez le format');
});
