import { act, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { MotionRows, useNewMessageMotion } from './Motion';

global.IS_REACT_ACT_ENVIRONMENT = true;
let container, root;
beforeEach(() => {
  jest.useFakeTimers();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.useRealTimers();
  delete window.matchMedia;
});
const render = async element => act(async () => root.render(element));

test('retire une ligne du clavier immédiatement puis du DOM et annule une sortie si elle revient', async () => {
  const list = keys => <MotionRows as="div">{keys.map(key => <div key={key}><button>{key}</button></div>)}</MotionRows>;
  await render(list(['a', 'b']));
  await render(list(['b']));
  const leaving = [...container.querySelectorAll('[data-motion-key]')].find(row => row.textContent === 'a');
  expect(leaving.getAttribute('aria-hidden')).toBe('true');
  expect(leaving.hasAttribute('inert')).toBe(true);
  await render(list(['a', 'b']));
  expect([...container.querySelectorAll('[inert]')]).toHaveLength(0);
  await render(list(['b']));
  await act(async () => jest.advanceTimersByTime(200));
  expect(container.textContent).toBe('b');
});

test('réduit les animations sans maintenir une ligne sortante', async () => {
  window.matchMedia = () => ({ matches: true });
  await render(<MotionRows as="div"><div key="a">a</div><div key="b">b</div></MotionRows>);
  await render(<MotionRows as="div"><div key="b">b</div></MotionRows>);
  expect(container.textContent).toBe('b');
});

test('anime uniquement les nouveaux messages de la même page sans demander de défilement', async () => {
  const animate = jest.fn(() => ({ cancel: jest.fn() }));
  const scroll = jest.fn();
  Element.prototype.animate = animate;
  Element.prototype.scrollIntoView = scroll;
  function Conversation({ page, messages }) {
    const ref = useRef(null);
    useNewMessageMotion(ref, page, messages);
    return <div ref={ref}>{messages.map(id => <article key={id} data-message-key={id}>{id}</article>)}</div>;
  }
  try {
    await render(<Conversation page="1" messages={['a']} />);
    expect(animate).not.toHaveBeenCalled();
    await render(<Conversation page="1" messages={['a', 'b']} />);
    expect(animate).toHaveBeenCalledTimes(1);
    await render(<Conversation page="2" messages={['c']} />);
    expect(animate).toHaveBeenCalledTimes(1);
    expect(scroll).not.toHaveBeenCalled();
  } finally {
    delete Element.prototype.animate;
    delete Element.prototype.scrollIntoView;
  }
});
