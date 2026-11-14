import {act} from 'react';
import {createRoot} from 'react-dom/client';
import ScrabbleGame from './ScrabbleGame';
import Menu from './OasisGameMenu';
import KaraokeStage from './KaraokeStage';
jest.mock('./useKaraokeAnalysis',()=>({useKaraokeAnalysis:()=>({data:null,status:'idle',error:'',reload:jest.fn()})}));
jest.mock('./useKaraokeVoice',()=>({useKaraokeVoice:()=>({voice:null,busy:false,error:'',toggle:jest.fn()})}));
jest.mock('./karaokeAudio',()=>({useKaraokeAudio:()=>({graphRef:{current:null},mix:jest.fn()})}));
jest.mock('./useKaraokeChrome',()=>({useKaraokeChrome:()=>({visible:true,wake:jest.fn()})}));
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');document.body.appendChild(host);root=createRoot(host);jest.useFakeTimers();});
afterEach(async()=>{if(root)await act(async()=>root.unmount());host.remove();jest.useRealTimers();});
function state(phase='playing'){
 return {mode:'scrabble',at:performance.now(),scrabble:{phase,board:Array.from({length:15},()=>Array(15).fill(null)),premiums:Array.from({length:15},()=>Array(15).fill('')),
  seats:[{id:'a',name:'Alice',connected:true,tiles:7},{id:'b',name:'Bob',connected:true,tiles:7}],score:[0,0],turn:1,
  round:1,round_id:'round',ply:0,rack:['A','M','I','S','E','T','?'],bag_count:88,history:[],chat:[],ready:[],spectators:0,settings:{seconds:180},remaining:180}};
}
function button(label){return [...host.querySelectorAll('button')].find(b=>b.textContent===label);}

test('menu opens the game with the normal host guard',async()=>{
 const send=jest.fn();
 await act(async()=>root.render(<Menu session={{}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>button('Jouer avec les mots →').click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'scrabble'});
});

test('rack placement asks the server for a preview and commits only its current validation',async()=>{
 const send=jest.fn(),data=state();
 const render=()=>root.render(<ScrabbleGame state={data} preview={data.scrabble_preview} userId="a" connected send={send}/>);
 await act(async()=>render());
 await act(async()=>host.querySelector('[aria-label="Lettre A, 1 point"]').click());
 await act(async()=>host.querySelector('[data-cell="112"]').click());
 await act(async()=>host.querySelector('[aria-label="Lettre M, 2 points"]').click());
 await act(async()=>host.querySelector('[data-cell="113"]').click());
 expect(button('Valider le mot').disabled).toBe(true);
 await act(async()=>jest.advanceTimersByTime(200));
 const packet=send.mock.calls.at(-1)[0];
 expect(packet.type).toBe('scr_preview');
 expect(packet.placements).toEqual([{row:7,column:7,index:0},{row:7,column:8,index:1}]);
 data.scrabble_preview={type:'scr_preview',request_id:packet.request_id,round_id:'round',ply:0,valid:true,score:6,words:[{word:'AM',score:6}]};
 await act(async()=>render());
 expect(button('Valider le mot').disabled).toBe(false);
 await act(async()=>button('Valider le mot').click());
 expect(send).toHaveBeenLastCalledWith({type:'scr_play',round_id:'round',ply:0,placements:packet.placements});
 // A preview for the old draft cannot authorize the changed placement.
 await act(async()=>host.querySelector('[data-cell="113"]').click());
 expect(button('Valider le mot').disabled).toBe(true);
});

test('joker asks for a letter and draft resets on an authoritative new turn',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<ScrabbleGame state={data} userId="a" connected send={send}/>));
 await act(async()=>host.querySelector('[aria-label="Lettre joker, 0 point"]').click());
 await act(async()=>host.querySelector('[data-cell="112"]').click());
 expect(host.querySelector('[role="dialog"]')).not.toBeNull();
 await act(async()=>button('Z').click());
 expect(host.querySelector('[data-cell="112"]').textContent).toContain('Z');
 data.scrabble={...data.scrabble,ply:1,turn:2};
 await act(async()=>root.render(<ScrabbleGame state={data} userId="a" connected send={send}/>));
 expect(host.querySelectorAll('.sg-pending')).toHaveLength(0);
 expect(button('Valider le mot').disabled).toBe(true);
});

test('exchange sends only selected rack indices and pass requires confirmation',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<ScrabbleGame state={data} userId="a" connected send={send}/>));
 await act(async()=>button('Échanger').click());
 await act(async()=>host.querySelector('[aria-label="Lettre A, 1 point"]').click());
 await act(async()=>button('Échanger les lettres').click());
 expect(send).toHaveBeenLastCalledWith({type:'scr_exchange',round_id:'round',ply:0,indices:[0]});
 await act(async()=>button('Passer').click());
 expect(host.querySelector('[role="dialog"]')).not.toBeNull();
 await act(async()=>button('Confirmer').click());
 expect(send).toHaveBeenLastCalledWith({type:'scr_pass',round_id:'round',ply:0});
});

test('spectators see the board and chat but have no rack or play permission',async()=>{
 const send=jest.fn(),data=state();data.scrabble.rack=[];
 data.scrabble.chat=[{id:'chat',name:'Bob',text:'<img src=x onerror=alert(1)>'}];
 await act(async()=>root.render(<ScrabbleGame state={data} userId="spectator" connected send={send}/>));
 expect(host.querySelectorAll('.sg-cell')).toHaveLength(225);
 expect(host.querySelector('.sg-rack')).toBeNull();
 expect(host.querySelector('[role="log"]').textContent).toContain('<img src=x');
 expect(host.querySelector('img')).toBeNull();
 await act(async()=>host.querySelector('[data-cell="112"]').click());
 expect(send).not.toHaveBeenCalled();
});

test('lobby seating, timing settings and host start share the server protocol',async()=>{
 const send=jest.fn(),data=state('lobby');data.scrabble.rack=[];
 await act(async()=>root.render(<ScrabbleGame state={data} userId="new" connected canControl send={send}/>));
 await act(async()=>button('Prendre une place').click());
 expect(send).toHaveBeenLastCalledWith({type:'scr_join',round_id:'round',ply:0});
 await act(async()=>button('Lancer la partie ').click());
 expect(send).toHaveBeenLastCalledWith({type:'scr_start',round_id:'round',ply:0});
});

test('disconnection blocks moves, keeps the existing rack and shows reconnection status',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<ScrabbleGame state={data} userId="a" connected={false} send={send}/>));
 expect(host.textContent).toContain('Reconnexion à OasisGame');
 expect(button('Valider le mot').disabled).toBe(true);
 expect(host.querySelector('.sg-rack').children).toHaveLength(7);
});

test.each([true,false])('private word verification survives periodic WebSocket snapshots (valid=%s)',async(valid)=>{
 const original=global.WebSocket;
 let socket;
 class Socket {
  static OPEN=1;
  readyState=1;
  send=jest.fn();close=jest.fn();
  constructor(){socket=this;}
 }
 global.WebSocket=Socket;
 try{
  const session={games:true,videoToken:'test',instanceId:'room',userId:'a',userName:'Alice',apiRoot:'/api'};
  await act(async()=>root.render(<KaraokeStage session={session}/>));
  await act(async()=>socket.onopen());
  const data=state();
  const sync=sequence=>socket.onmessage({data:JSON.stringify({...data,type:'kstate',sequence,host_id:'a'})});
  await act(async()=>sync(1));
  await act(async()=>host.querySelector('[aria-label="Lettre A, 1 point"]').click());
  await act(async()=>host.querySelector('[data-cell="112"]').click());
  await act(async()=>host.querySelector('[aria-label="Lettre M, 2 points"]').click());
  await act(async()=>host.querySelector('[data-cell="113"]').click());
  await act(async()=>jest.advanceTimersByTime(200));
  const packet=socket.send.mock.calls.map(([raw])=>JSON.parse(raw)).findLast(m=>m.type==='scr_preview');
  expect(packet).toBeDefined();
  await act(async()=>socket.onmessage({data:JSON.stringify({type:'scr_preview',request_id:packet.request_id,
   round_id:'round',ply:0,valid,score:6,words:[{word:'AM',score:6}],detail:'Mot absent du lexique français : AM'})}));
  expect(button('Valider le mot').disabled).toBe(!valid);
  for(let sequence=2;sequence<=4;sequence++){
   await act(async()=>jest.advanceTimersByTime(5000));
   await act(async()=>sync(sequence));
   expect(host.textContent).not.toContain('Vérification du mot…');
   expect(button('Valider le mot').disabled).toBe(!valid);
   expect(host.textContent).toContain(valid?'+ 6 points':'Mot absent du lexique français : AM');
  }
  if(valid){
   await act(async()=>button('Valider le mot').click());
   expect(JSON.parse(socket.send.mock.calls.at(-1)[0])).toEqual({type:'scr_play',round_id:'round',ply:0,placements:packet.placements});
  }
 }finally{
  await act(async()=>root.unmount());
  root=null;
  global.WebSocket=original;
 }
});
