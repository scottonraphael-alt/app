import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Lyrics from './KaraokeLyrics';
global.IS_REACT_ACT_ENVIRONMENT = true;

test('each small Japanese group keeps its own ruby, timing and colored copy', async () => {
  let frame;
  const raf = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => {frame = cb; return 1;});
  const cancel = jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  const host = document.createElement('div'), root = createRoot(host);
  const tokens = [{t:'こ',r:'ko',s:0,e:.1},{t:'の',r:'no',s:.1,e:.2},{t:'宇宙',r:'sora',s:.2,e:1,reading_locked:true}];
  try {
    await act(async () => root.render(<Lyrics lines={[{t:0,e:1,tokens}]} getTime={()=>.3} showRomaji />));
    await act(async () => frame());
    expect([...host.querySelectorAll('.kl-base ruby')].map(r=>r.firstChild.textContent)).toEqual(['こ','の','宇宙']);
    expect([...host.querySelectorAll('.kl-base rt')].map(r=>r.textContent)).toEqual(['ko','no','sora']);
    expect([...host.querySelectorAll('.kl-fill rt')].map(r=>r.textContent)).toEqual(['ko','no','sora']);
    expect(host.querySelectorAll('.kl-tok')).toHaveLength(3);
  } finally { await act(async()=>root.unmount()); raf.mockRestore(); cancel.mockRestore(); }
});
