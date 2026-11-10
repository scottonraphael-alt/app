import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Menu from './OasisGameMenu';
import Setup from './BlindTestSetup';
import BoardGame from './BoardGame';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());delete global.fetch;});
const session={videoToken:'test',apiRoot:'/api',games:true,channelId:'wrong',karaokeChannelId:'1569069812804751431',guildId:'guild'};
test('main menu disables karaoke outside its channel but permits preparing a blind test',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={session} state={{mode:'menu'}} canControl send={send}/>));
 const buttons=[...host.querySelectorAll('button')];
 expect(buttons.find(b=>b.textContent.includes('Entrer sur scène')).disabled).toBe(true);
 await act(async()=>buttons.find(b=>b.textContent.includes('Préparer une partie')).click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'blindtest_setup'});
 expect(host.querySelector('a').href).toContain('1569069812804751431');
});
test('correct channel enables karaoke and guests wait for the host',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={{...session,channelId:session.karaokeChannelId}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent.includes('Entrer sur scène')).click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'karaoke'});
 await act(async()=>root.render(<Menu session={session} state={{mode:'menu'}} canControl={false} send={send}/>));
 expect([...host.querySelectorAll('button')].every(b=>b.disabled)).toBe(true);
});
test('full blind test setup sends launch with configured settings rather than hiding the lyrics',async()=>{
 const send=jest.fn(),setStarting=jest.fn();
 await act(async()=>root.render(<Setup session={session} settings={{pool:'local',rounds:10,seconds:20,style:'',decade:''}} setSettings={jest.fn()} library={[]} localTracks={[]} plays setPlays={jest.fn()} starting={false} setStarting={setStarting} categoryLoading={false} setCategoryLoading={jest.fn()} connected send={send} setNotice={jest.fn()}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Lancer la partie').click());
 expect(setStarting).toHaveBeenCalledWith(true);expect(send).toHaveBeenCalledWith({type:'bt_start',pool:'local',rounds:10,seconds:20,style:'',decade:''});
 expect(host.querySelector('section').getAttribute('aria-label')).toBe('Préparer un blind test');
});

test('the host can open Puissance 4 from the shared games menu', async () => {
 const send = jest.fn();
 await act(async () => root.render(<Menu session={session} state={{ mode: 'menu' }} canControl send={send} />));
 await act(async () => [...host.querySelectorAll('button')].find(button => button.textContent.includes('Ouvrir le plateau')).click());
 expect(send).toHaveBeenCalledWith({ type: 'choose_game', game: 'connect_four' });
});

test('only the active player can drop a token from the board', async () => {
 const send = jest.fn();
 const state = {
   at: performance.now(),
   mode: 'connect_four',
   connect_four: {
     phase: 'playing', board: [[0, 0], [1, 0]], settings: { size: 'classic', seconds: 0 },
     turn: 2, round: 1, round_id: 'round', remaining: null, score: [0, 0], spectators: 1,
     seats: [{ id: 'a', name: 'Alice', connected: true }, { id: 'b', name: 'Bob', connected: true }],
     history: [{ row: 1, column: 0, player: 1 }],
   },
 };
 await act(async () => root.render(<BoardGame state={state} userId="spectator" connected send={send} />));
 const second = () => host.querySelectorAll('.bg-column')[1];
 expect(second().getAttribute('aria-disabled')).toBe('true');
 await act(async () => second().click());
 expect(send).not.toHaveBeenCalled();
 await act(async () => root.render(<BoardGame state={state} userId="b" connected send={send} />));
 expect(second().getAttribute('aria-disabled')).toBe('false');
 await act(async () => second().click());
 expect(send).toHaveBeenCalledWith({ type: 'c4_drop', round_id: 'round', column: 1, ply: 1 });
});

test('the host can open the morpion from the games menu', async () => {
 const send = jest.fn();
 await act(async () => root.render(<Menu session={session} state={{ mode: 'menu' }} canControl send={send} />));
 const button = [...host.querySelectorAll('button')].find(item => item.textContent.includes('Jouer au morpion'));
 await act(async () => button.click());
 expect(send).toHaveBeenCalledWith({ type: 'choose_game', game: 'tic_tac_toe' });
});

test('the morpion sends the selected free cell and leaves occupied cells disabled', async () => {
 const send = jest.fn();
 const state = {
   at: performance.now(), mode: 'tic_tac_toe',
   tic_tac_toe: {
     phase: 'playing', board: [[1, 0, 0], [0, 0, 0], [0, 0, 0]],
     settings: { seconds: 0 }, turn: 2, round: 1, round_id: 'round', remaining: null,
     score: [0, 0], spectators: 0,
     seats: [{ id: 'a', name: 'Alice', connected: true }, { id: 'b', name: 'Bob', connected: true }],
     history: [{ row: 0, column: 0, player: 1 }],
   },
 };
 await act(async () => root.render(<BoardGame state={state} userId="b" connected send={send} />));
 const cells = host.querySelectorAll('.bg-cell');
 expect(cells).toHaveLength(9);
 expect(cells[0].getAttribute('aria-disabled')).toBe('true');
 await act(async () => cells[0].click());
 expect(send).not.toHaveBeenCalled();
 await act(async () => cells[4].click());
 expect(send).toHaveBeenCalledWith({ type: 'ttt_place', round_id: 'round', cell: 4, ply: 1 });
});
