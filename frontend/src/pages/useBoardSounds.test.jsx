import { act } from "react";
import { createRoot } from "react-dom/client";
import { useBoardSounds } from "./useBoardSounds";

global.IS_REACT_ACT_ENVIRONMENT = true;

function Fixture({ ply, roundId }) {
  const { unlock, toggle } = useBoardSounds("tic_tac_toe", roundId, ply, true);
  return <button onClick={unlock} onDoubleClick={toggle}>Bruitages</button>;
}

test("sound plays once per confirmed move and stays silent for a snapshot, rematch or mute", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const previousAudio = window.AudioContext;
  const start = jest.fn();
  const param = { setValueAtTime: jest.fn(), exponentialRampToValueAtTime: jest.fn() };
  window.AudioContext = class {
    state = "running";
    currentTime = 0;
    close = () => Promise.resolve();
    createOscillator = () => ({ frequency: param, connect: jest.fn(), start, stop: jest.fn() });
    createGain = () => ({ gain: param, connect: jest.fn(), disconnect: jest.fn() });
  };

  const render = (ply, roundId = "round") => act(async () => root.render(<Fixture {...{ ply, roundId }} />));
  try {
    await render(2);
    await act(async () => host.querySelector("button").click());
    expect(start).not.toHaveBeenCalled();
    await render(3);
    expect(start).toHaveBeenCalledTimes(2);
    await render(3);
    await render(0, "rematch");
    expect(start).toHaveBeenCalledTimes(2);
    await act(async () => host.querySelector("button").dispatchEvent(new MouseEvent("dblclick", { bubbles: true })));
    await render(1, "rematch");
    expect(start).toHaveBeenCalledTimes(2);
  } finally {
    await act(async () => root.unmount());
    window.AudioContext = previousAudio;
    localStorage.removeItem("oasisgame.board-sounds");
  }
});
