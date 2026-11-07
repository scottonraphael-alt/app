import { act } from 'react';
import { createRoot } from 'react-dom/client';
import Categories from './BlindTestCategories';
import { karaokeRequest } from './KaraokeTools';
jest.mock('./KaraokeTools', () => ({ karaokeRequest: jest.fn() }));
global.IS_REACT_ACT_ENVIRONMENT = true;
let host, root;
const session = { videoToken: 'signed', apiRoot: '/api' };
const options = {
  styles: [{id:'anime',label:'Animé'}, {id:'rock',label:'Rock'}, {id:'jpop',label:'J-pop'}],
  decades: Array.from({length:8},(_,i)=>({id:String(1950+i*10),label:'Années '+(1950+i*10)})),
};
beforeEach(() => {
  jest.useFakeTimers();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  karaokeRequest.mockImplementation(async (_, path) => path.endsWith('/categories') ? options : {count:12});
});
afterEach(async () => { await act(async()=>root.unmount());host.remove();jest.useRealTimers();jest.clearAllMocks(); });
test('combine style et décennie, charge le nombre et ne récupère aucune réponse musicale', async () => {
  const onChange=jest.fn(),onLoading=jest.fn();
  await act(async()=>root.render(<Categories session={session} style="" decade="" onChange={onChange} onLoading={onLoading}/>));
  const select=host.querySelector('[aria-label="Décennie Deezer"]');
  expect(select.options).toHaveLength(9);
  expect(select.textContent).toContain('Années 1950');
  expect(select.textContent).toContain('Années 2020');
  await act(async()=>{select.value='1980';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(onChange).toHaveBeenCalledWith({style:'',decade:'1980'});
  await act(async()=>root.render(<Categories session={session} style="rock" decade="1980" onChange={onChange} onLoading={onLoading}/>));
  expect(onLoading).toHaveBeenLastCalledWith(true);
  await act(async()=>jest.advanceTimersByTime(260));
  expect(karaokeRequest).toHaveBeenCalledWith(session,'/catalog/category',expect.objectContaining({query:{style:'rock',decade:'1980'}}));
  expect(host.textContent).toContain('12 extraits');
  expect(onLoading).toHaveBeenLastCalledWith(false);
});
test('une combinaison vide reste explicite',async()=>{
  karaokeRequest.mockImplementation(async(_,path)=>path.endsWith('/categories')?options:{count:0});
  await act(async()=>root.render(<Categories session={session} style="anime" decade="1950" onChange={jest.fn()} onLoading={jest.fn()}/>));
  await act(async()=>jest.advanceTimersByTime(260));
  expect(host.textContent).toContain('Aucun extrait pour cette combinaison');
});
