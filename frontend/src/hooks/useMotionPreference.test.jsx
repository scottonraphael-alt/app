import {act} from 'react';
import {createRoot} from 'react-dom/client';
import useMotionPreference,{MOTION_EVENT} from './useMotionPreference';
import {MotionRows,motionAllowed,useReducedMotion} from '../components/motion/Motion';
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,container;
beforeEach(()=>{localStorage.clear();delete document.documentElement.dataset.motion;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);window.matchMedia=()=>({matches:false,addEventListener:jest.fn(),removeEventListener:jest.fn()});});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();delete document.documentElement.dataset.motion;delete window.matchMedia;jest.restoreAllMocks();});
function Control(){const {reduced,toggle}=useMotionPreference();return <button onClick={toggle}>{reduced?'Réduit':'Automatique'}</button>;}
function Observer(){const reduced=useReducedMotion();return <output>{String(reduced)}</output>;}
test('synchronizes controls and the animation engine immediately, persists after remount',async()=>{
 await act(async()=>root.render(<><Control/><Control/><Observer/></>));
 await act(async()=>container.querySelector('button').click());
 expect([...container.querySelectorAll('button')].map(b=>b.textContent)).toEqual(['Réduit','Réduit']);
 expect(container.querySelector('output').textContent).toBe('true');expect(motionAllowed()).toBe(false);expect(localStorage.getItem('iris.motion')).toBe('reduced');
 await act(async()=>root.render(null));await act(async()=>root.render(<Control/>));expect(container.textContent).toBe('Réduit');
 await act(async()=>container.querySelector('button').click());expect(motionAllowed()).toBe(true);
});
test('system reduction is respected even if user preference is automatic',async()=>{
 window.matchMedia=()=>({matches:true});await act(async()=>root.render(<><Control/><Observer/></>));
 expect(container.querySelector('output').textContent).toBe('true');expect(motionAllowed()).toBe(false);
});
test('manual reduction removes departing rows without waiting for an animation',async()=>{
 const render=keys=>root.render(<><Control/><MotionRows as="div">{keys.map(k=><button key={k}>{k}</button>)}</MotionRows></>);
 await act(async()=>render(['a','b']));await act(async()=>container.querySelector('button').click());await act(async()=>render(['b']));
 expect(container.querySelector('[data-exiting]')).toBeNull();expect(container.textContent).toBe('Réduitb');
});
test('local reduction works when browser storage is unavailable',async()=>{
 jest.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('Unavailable');});
 await act(async()=>root.render(<><Control/><Observer/></>));await act(async()=>container.querySelector('button').click());
 expect(container.querySelector('output').textContent).toBe('true');await act(async()=>container.querySelector('button').click());expect(motionAllowed()).toBe(true);
});
test('storage changes update open controls and the active animation observer',async()=>{
 await act(async()=>root.render(<><Control/><Observer/></>));
 await act(async()=>{localStorage.setItem('iris.motion','reduced');window.dispatchEvent(new StorageEvent('storage',{key:'iris.motion'}));});
 expect(document.documentElement.dataset.motion).toBe('reduced');expect(container.querySelector('output').textContent).toBe('true');
 expect(MOTION_EVENT).toBe('iris-motion-change');
});
