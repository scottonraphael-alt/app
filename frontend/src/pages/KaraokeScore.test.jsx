import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Score from './KaraokeScore';
import Intermission from './KaraokeIntermission';
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,host;
beforeEach(()=>{jest.useFakeTimers();host=document.createElement('div');root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());jest.useRealTimers();});
test('awards reflect server maximum and reset between songs',async()=>{
 const render=async(points,points_max,run_id='song')=>act(async()=>root.render(<Score score={{points,points_max,run_id}}/>));
 await render(0,0);await render(1000,1000);expect(host.querySelector('.ks-perfect').textContent).toContain('+1');
 await render(1600,1800);expect(host.querySelector('.ks-good')).not.toBeNull();
 await render(1700,2600);expect(host.querySelector('.ks-low')).not.toBeNull();
 await render(0,0,'next');expect(host.querySelector('.ks-award')).toBeNull();expect(host.querySelector('strong').textContent).toBe('0');
});
test('all members can pause countdown while skipping is host-only',async()=>{
 const send=jest.fn(),value={id:'end',deadline:Date.now()/1000+70,remaining:70,paused:false};
 await act(async()=>root.render(<Intermission value={value} send={send} canControl={false}/>));
 expect(host.textContent).toContain('1:10');expect(host.textContent).not.toContain('Passer au suivant');
 await act(async()=>host.querySelector('button').click());expect(send).toHaveBeenCalledWith({type:'autoplay_pause',id:'end',paused:true});
 await act(async()=>root.render(<Intermission value={{...value,paused:true}} send={send} canControl/>));
 expect(host.textContent).toContain('En pause');expect(host.textContent).toContain('Passer au suivant');
});
