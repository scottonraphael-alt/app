import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Welcome from './KaraokeWelcome';
import Rankings from './KaraokeRankings';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{jest.useFakeTimers();host=document.createElement('div');root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());jest.useRealTimers();delete global.fetch;});
test('welcome shows shared countdown and join button without granting voice consent',async()=>{
 const join=jest.fn();
 await act(async()=>root.render(<Welcome value={{deadline:Date.now()/1000+20}} players={[{id:'a',name:'Alice',plays:true}]} plays={false} setPlays={join}/>));
 expect(host.textContent).toContain('20');expect(host.textContent).toContain('Alice');
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Je participe').click());
 expect(join).toHaveBeenCalled();
 await act(async()=>jest.advanceTimersByTime(5000));expect(host.querySelector('.kw-countdown').textContent).toBe('15secondes');
});
test('rankings can switch between current song and overall',async()=>{
 const requests=[];global.fetch=jest.fn(async url=>{requests.push(url);return {ok:true,json:async()=>({rows:[{rank:1,id:'a',name:'Alice',points:1200,songs:2}]})};});
 const session={videoToken:'signed',userId:'a',apiRoot:'/api'};
 await act(async()=>root.render(<Rankings session={session} open onClose={()=>{}} track={{id:'song'}} tracks={[{id:'song',title:'Song',artist:'Artist'}]}/>));
 expect(requests[requests.length-1]).toContain('track_id=song');expect(host.textContent).toContain('Alice');
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Général').click());
 expect(requests[requests.length-1]).not.toContain('track_id=');expect(host.textContent).toContain('2 chansons');
});
