import { act, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { useKaraokeAudio, preparedEnergy, readEnergy } from './karaokeAudio';

global.IS_REACT_ACT_ENVIRONMENT = true;
let root, host, sources, scheduled;
class Media extends EventTarget {
  constructor(){super();Object.assign(this,{readyState:3,currentTime:0,playbackRate:1,paused:false,ended:false,seeking:false,volume:1});}
  play=jest.fn(async()=>{this.paused=false;});
  pause=jest.fn(()=>{this.paused=true;});
  removeAttribute=jest.fn();
}
class Context {
  constructor(){this.state='running';this.currentTime=0;this.destination={};}
  createMediaElementSource(){sources++;return {connect:jest.fn()};}
  createAnalyser(){return {connect:jest.fn(),getFloatTimeDomainData:jest.fn(),getByteFrequencyData:jest.fn()};}
  createGain(){const gain={value:1};gain.setTargetAtTime=jest.fn(value=>{gain.value=value;});return {gain,connect:jest.fn()};}
  resume=jest.fn(async()=>{});
  close=jest.fn(async()=>{this.state='closed';});
  decodeAudioData=jest.fn(async()=>({duration:120}));
  createBufferSource(){const source={connect:jest.fn(),disconnect:jest.fn(),stop:jest.fn(),start:jest.fn(),playbackRate:{value:1}};scheduled.push(source);return source;}
}
beforeEach(()=>{
  jest.useFakeTimers();sources=0;scheduled=[];window.AudioContext=Context;
  global.fetch=jest.fn(async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(8)}));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();jest.clearAllTimers();jest.useRealTimers();delete window.AudioContext;delete global.fetch;});

test('mixe les pistes localement, synchronise un saut et revient à l’original sur erreur',async()=>{
  const master=new Media(),inst=new Media(),voice=new Media();
  let graph;
  function Player({guide}){
    const audioRef=useRef(master),instrumentalRef=useRef(inst),vocalRef=useRef(voice);
    const value=useKaraokeAudio({audioRef,instrumentalRef,vocalRef,stems:true,audioUrl:'/audio?t=signed&id=song',volume:.8,guide});
    graph=value.graphRef;
    return <p>{value.mix}</p>;
  }
  await act(async()=>root.render(<Player guide={.5}/>));
  await act(async()=>master.dispatchEvent(new Event('play')));
  expect(sources).toBe(3);
  expect(graph.current.channels.map(channel=>channel.gain.gain.value)).toEqual([0,.8,.5]);
  await act(async()=>root.render(<Player guide={0}/>));
  expect(graph.current.channels.map(channel=>channel.gain.gain.value)).toEqual([0,.8,0]);
  master.currentTime=34;
  await act(async()=>master.dispatchEvent(new Event('seeked')));
  expect(scheduled.slice(-2).map(source=>source.start.mock.calls[0])).toEqual([[.035,34.035],[.035,34.035]]);
  await act(async()=>master.dispatchEvent(new Event('waiting')));
  expect(scheduled.slice(-2).every(source=>source.stop.mock.calls.length===1)).toBe(true);
  await act(async()=>master.dispatchEvent(new Event('playing')));
  expect(scheduled.slice(-2).map(source=>source.start.mock.calls[0])).toEqual([[.035,34.035],[.035,34.035]]);
  expect(inst.play).not.toHaveBeenCalled();expect(voice.play).not.toHaveBeenCalled();
  global.fetch.mockResolvedValue({ok:false});
  await act(async()=>root.render(<Player guide={.1} key="retry"/>));
  expect(host.textContent).toBe('fallback');
  expect(graph.current.channels.map(channel=>channel.gain.gain.value)).toEqual([.8,0,0]);
  expect(master.paused).toBe(false);
});

test('réutilise les sources Web Audio pendant un remontage React sans couper le son',async()=>{
  const audioRef={current:new Media()},instrumentalRef={current:new Media()},vocalRef={current:new Media()};
  function Player(){useKaraokeAudio({audioRef,instrumentalRef,vocalRef,stems:false,audioUrl:'',volume:.5,guide:1});return null;}
  await act(async()=>root.render(<Player/>));
  await act(async()=>audioRef.current.dispatchEvent(new Event('play')));
  expect(sources).toBe(3);
  await act(async()=>root.render(null));
  await act(async()=>root.render(<Player/>));
  await act(async()=>audioRef.current.dispatchEvent(new Event('play')));
  expect(sources).toBe(3);
});

test('les deux pistes partagent une horloge même après une longue période sans timer JS',async()=>{
  const audioRef={current:new Media()},instrumentalRef={current:new Media()},vocalRef={current:new Media()};
  let graph;
  function Player(){const value=useKaraokeAudio({audioRef,instrumentalRef,vocalRef,stems:true,audioUrl:'/audio?id=song',volume:1,guide:1});graph=value.graphRef;return null;}
  await act(async()=>root.render(<Player/>));
  expect(scheduled).toHaveLength(2);
  expect(scheduled[0].start.mock.calls[0]).toEqual(scheduled[1].start.mock.calls[0]);
  graph.current.context.currentTime=100;audioRef.current.currentTime=100;
  await act(async()=>audioRef.current.dispatchEvent(new Event('timeupdate')));
  expect(scheduled).toHaveLength(2); // No independent media clock or progressive correction.
  audioRef.current.playbackRate=1.25;
  await act(async()=>audioRef.current.dispatchEvent(new Event('ratechange')));
  expect(scheduled).toHaveLength(4);
  expect(scheduled[2].start.mock.calls[0]).toEqual(scheduled[3].start.mock.calls[0]);
  expect(scheduled.slice(-2).map(source=>source.playbackRate.value)).toEqual([1.25,1.25]);
});

test('la carte préparée anticipe un drop et les mesures live restent bornées',()=>{
  const map={step:.1,instrumental:Array(20).fill(50),vocals:Array(20).fill(25),beats:[1],drops:[1.2]};
  const value=preparedEnergy(map,1);
  expect(value.energy).toBe(.5);expect(value.vocals).toBe(.25);expect(value.beat).toBe(true);
  expect(value.tension).toBeGreaterThan(.8);
  expect(preparedEnergy(map,1.2).drop).toBe(true);
  const result=readEnergy({getFloatTimeDomainData:array=>array.fill(.1),getByteFrequencyData:array=>array.fill(64)},
    {wave:new Float32Array(1024),bins:new Uint8Array(512)});
  expect(result.energy).toBeCloseTo(.4);expect(result.bass).toBeCloseTo(64/255);
});
