import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {useKaraokeVoice} from './useKaraokeVoice';
import {useKaraokeChrome} from './useKaraokeChrome';
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,host,result;
const session={videoToken:'signed',instanceId:'room',channelId:'123456789012345678',apiRoot:'/api'};
function Player(){result=useKaraokeVoice(session,true);return null;}
beforeEach(()=>{jest.useFakeTimers();host=document.createElement('div');root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());jest.clearAllTimers();jest.useRealTimers();delete global.fetch;});
test('joins automatically but analysis requires the explicit score button and a second click revokes it',async()=>{
 global.fetch=jest.fn(async(url,options)=>({ok:true,json:async()=>url.includes('/status')?{connected:false,scores:[]}:url.includes('/ensure')?{status:'connected'}:{enabled:JSON.parse(options.body).enabled}}));
 await act(async()=>root.render(<Player/>));
 expect(fetch.mock.calls.filter(([u])=>u.includes('/ensure'))).toHaveLength(1);
 expect(fetch.mock.calls.some(([u])=>u.includes('/consent'))).toBe(false);
 await act(async()=>result.toggle());
 expect(result.voice.consented).toBe(true);
 await act(async()=>result.toggle());
 expect(result.voice.consented).toBe(false);
 expect(fetch.mock.calls.filter(([u])=>u.includes('/consent')).map(([,o])=>JSON.parse(o.body).enabled)).toEqual([true,false]);
});
test('controls fade after inactivity and wake on activity, menus hold them visible',async()=>{
 function Chrome({paused}){result=useKaraokeChrome(paused);return null;}
 await act(async()=>root.render(<Chrome paused={false}/>));
 await act(async()=>jest.advanceTimersByTime(3200));expect(result.visible).toBe(false);
 await act(async()=>result.wake());expect(result.visible).toBe(true);
 await act(async()=>root.render(<Chrome paused/>));
 await act(async()=>jest.advanceTimersByTime(10000));expect(result.visible).toBe(true);
});
