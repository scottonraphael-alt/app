import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {useKaraokeAnalysis} from './useKaraokeAnalysis';
global.IS_REACT_ACT_ENVIRONMENT=true;
let root,host,result;
const props={trackId:'first',apiRoot:'/api',token:'test',revision:0};
function Player(p){result=useKaraokeAnalysis(p);return null;}
beforeEach(()=>{jest.useFakeTimers();host=document.createElement('div');root=createRoot(host);global.fetch=jest.fn();});
afterEach(async()=>{await act(async()=>root.unmount());jest.clearAllTimers();jest.useRealTimers();delete global.fetch;});
const response=data=>({ok:true,status:200,json:async()=>data});

test('retries an incomplete import and exposes notes when the server becomes ready',async()=>{
 fetch.mockResolvedValueOnce(response({available:false})).mockResolvedValueOnce(response({available:true,notes:[{midi:60}]}));
 await act(async()=>root.render(<Player {...props}/>));
 expect(result.status).toBe('loading');
 await act(async()=>jest.advanceTimersByTime(2000));
 expect(result.status).toBe('ready');expect(result.data.notes).toHaveLength(1);
 expect(fetch.mock.calls[0][1].cache).toBe('no-store');
});
test('stops bounded retries, offers manual reload and clears timers on exit',async()=>{
 fetch.mockResolvedValue(response({available:false}));
 await act(async()=>root.render(<Player {...props}/>));
 for(const delay of [2000,5000,10000]) await act(async()=>jest.advanceTimersByTime(delay));
 expect(result.status).toBe('unavailable');expect(fetch).toHaveBeenCalledTimes(4);
 fetch.mockResolvedValue(response({available:true,notes:[{}]}));
 await act(async()=>result.reload());
 expect(result.status).toBe('ready');
});
test('does not retry authorization failures or publish a stale track response',async()=>{
 fetch.mockResolvedValueOnce({ok:false,status:403});
 await act(async()=>root.render(<Player {...props}/>));
 expect(result.status).toBe('unavailable');
 await act(async()=>jest.advanceTimersByTime(20000));
 expect(fetch).toHaveBeenCalledTimes(1);
 let resolve;
 fetch.mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockResolvedValueOnce(response({available:true,version:'second',notes:[{}]}));
 await act(async()=>root.render(<Player {...props} trackId="old"/>));
 await act(async()=>root.render(<Player {...props} trackId="new"/>));
 await act(async()=>resolve(response({available:true,version:'stale'})));
 expect(result.data.version).toBe('second');
});
