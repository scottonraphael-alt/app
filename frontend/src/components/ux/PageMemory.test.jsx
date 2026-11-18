import { PageMemoryProvider, usePageMemoryState, usePageReturnPosition } from './PageMemory';
import { useState, act } from 'react';
import { createRoot } from 'react-dom/client';
global.IS_REACT_ACT_ENVIRONMENT = true;
let container, root;
function render(node){act(()=>root.render(node));return {rerender:next=>act(()=>root.render(next))};}
const screen={getByLabelText:label=>container.querySelector(`[aria-label="${label}"]`),getByRole:(role,{name})=>[...container.querySelectorAll(role==='link'?'a':role)].find(el=>el.textContent===name)};
const fireEvent={click:el=>act(()=>el.click()),scroll:el=>act(()=>el.dispatchEvent(new Event('scroll'))),wheel:el=>act(()=>el.dispatchEvent(new Event('wheel'))),change:(el,{target:{value}})=>act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));})};
let mockLocation={pathname:'/list',key:'list',hash:''},mockNavigation='POP',mockGo;
jest.mock('react-router-dom',()=>({useLocation:()=>mockLocation,useNavigationType:()=>mockNavigation}),{virtual:true});
let visits, height, resize;
function NavigationMemory() { usePageReturnPosition(); return null; }
function List() {
  const [filter, setFilter] = usePageMemoryState('list.filter', '');
  const [ready, setReady] = useState(() => visits++ === 0);
  return <div className="app-main"><input aria-label="Filtre" value={filter} onChange={e => setFilter(e.target.value)}/>{ready ? <a className="cw-case-link" href="/detail" onClick={e=>{e.preventDefault();mockGo("detail");}}>Dossier Camille</a> : <button onClick={() => {height = 2400; setReady(true);}}>Charger les dossiers</button>}</div>;
}
function Fixture({ account = 'a' }) {
 const [route,setRoute]=useState('list');
 mockLocation={pathname:`/${route}`,key:route,hash:''};
 mockGo=next=>{mockNavigation=next==='list'?'POP':'PUSH';setRoute(next);};
 return <PageMemoryProvider key={account}><NavigationMemory/>{route==='list'?<List/>:<button onClick={()=>mockGo('list')}>Retour</button>}</PageMemoryProvider>;
}
const originalScroll = window.scrollTo, originalObserver = window.ResizeObserver;
const originalY = Object.getOwnPropertyDescriptor(window, 'scrollY');
const originalHeight = Object.getOwnPropertyDescriptor(document.documentElement, 'scrollHeight');
beforeEach(() => {
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
  visits = 0; height = 2400; resize = null;mockNavigation='POP';
  Object.defineProperty(window, 'scrollY', {configurable:true,writable:true,value:0});
  Object.defineProperty(document.documentElement, 'scrollHeight', {configurable:true,get:()=>height});
  window.scrollTo = jest.fn(({top}) => {window.scrollY = top;});
  window.ResizeObserver = class {constructor(callback){resize=callback;} observe(){} disconnect(){}};
});
afterEach(() => {
  act(()=>root.unmount());container.remove();
  window.scrollTo = originalScroll; window.ResizeObserver = originalObserver;
  Object.defineProperty(window, 'scrollY', originalY);
  if(originalHeight) Object.defineProperty(document.documentElement,'scrollHeight',originalHeight);
  else delete document.documentElement.scrollHeight;
});
test('retains list filters across navigation and clears them when the account changes', () => {
  const view = render(<Fixture/>);
  fireEvent.change(screen.getByLabelText('Filtre'),{target:{value:'Camille'}});
  fireEvent.click(screen.getByRole('link',{name:'Dossier Camille'}));
  fireEvent.click(screen.getByRole('button',{name:'Retour'}));
  expect(screen.getByLabelText('Filtre').value).toBe('Camille');
  view.rerender(<Fixture account="b"/>);
  expect(screen.getByLabelText('Filtre').value).toBe('');
});
test('waits for returning list content before restoring scroll and the selected link', () => {
  render(<Fixture/>);
  window.scrollY = 750; fireEvent.scroll(window);
  fireEvent.click(screen.getByRole('link',{name:'Dossier Camille'})); height = 200;
  fireEvent.click(screen.getByRole('button',{name:'Retour'}));
  fireEvent.click(screen.getByRole('button',{name:'Charger les dossiers'})); act(() => resize());
  expect(window.scrollTo).toHaveBeenLastCalledWith({top:750,left:0,behavior:'instant'});
  expect(document.activeElement).toBe(screen.getByRole('link',{name:'Dossier Camille'}));
  expect(screen.getByRole('link',{name:'Dossier Camille'}).classList.contains('iris-return-target')).toBe(true);
});
test('user scrolling cancels pending restoration', () => {
  render(<Fixture/>); window.scrollY=750; fireEvent.scroll(window);
  fireEvent.click(screen.getByRole('link',{name:'Dossier Camille'})); height=200;
  fireEvent.click(screen.getByRole('button',{name:'Retour'})); fireEvent.wheel(window);
  window.scrollTo.mockClear();
  fireEvent.click(screen.getByRole('button',{name:'Charger les dossiers'})); act(() => resize());
  expect(window.scrollTo).not.toHaveBeenCalled();
});
