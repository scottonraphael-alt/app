import { useEffect, useRef, useState } from 'react';

const graphs = new WeakMap();
const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));

function graphFor(elements) {
  const master = elements[0];
  let graph = graphs.get(master);
  if (graph) { clearTimeout(graph.dispose); return graph; }
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) return null;
  const context = new Context();
  const channels = elements.map(element => {
    const source = context.createMediaElementSource(element);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = .55;
    const gain = context.createGain();
    source.connect(analyser); analyser.connect(gain); gain.connect(context.destination);
    element.volume = 1;
    return { analyser, gain };
  });
  graph = { context, channels, dispose: null };
  graphs.set(master, graph);
  return graph;
}

/** Every gain is local; no playback or mixing preference is sent to the server. */
export function useKaraokeAudio({ audioRef, instrumentalRef, vocalRef, stems, audioUrl, volume, guide, retry = 0 }) {
  const graphRef = useRef(null);
  const ready = useRef(false);
  const options = useRef({ volume, guide });
  options.current = { volume, guide };
  const [mix, setMix] = useState('original');
  const applyGains = useRef(() => {});
  useEffect(() => {
    const elements = [audioRef.current, instrumentalRef.current, vocalRef.current];
    const master = elements[0];
    if (elements.some(element => !element)) return;
    const existing = graphs.get(master);
    if (existing) { clearTimeout(existing.dispose); graphRef.current = existing; }
    const gains = () => {
      const { volume: level, guide: voice } = options.current;
      const values = ready.current ? [0, clamp(level), clamp(level)*clamp(voice)] : [clamp(level), 0, 0];
      const graph = graphRef.current;
      elements.forEach((element, index) => {
        if (graph) graph.channels[index].gain.gain.setTargetAtTime(values[index], graph.context.currentTime, .025);
        else element.volume = values[index];
      });
    };
    applyGains.current = gains;
    const activate = () => {
      try {
        graphRef.current = graphFor(elements);
        graphRef.current?.context.resume().catch(() => {});
        gains();
      } catch {
        // Native element mixing still works on browsers without Web Audio.
        gains();
      }
    };
    master.addEventListener('play', activate);
    window.addEventListener('pointerdown', activate);
    gains();
    return () => {
      master.removeEventListener('play', activate);
      window.removeEventListener('pointerdown', activate);
      const graph = graphRef.current;
      if (graph) graph.dispose = setTimeout(() => {
        graph.context.close().catch(() => {});
        graphs.delete(master);
      }, 0);
      elements.slice(1).forEach(element => element.pause());
    };
  }, [audioRef, instrumentalRef, vocalRef]);
  useEffect(() => { applyGains.current(); }, [volume, guide]);
  useEffect(() => {
    const master = audioRef.current, inst = instrumentalRef.current, voice = vocalRef.current;
    if (!master || !inst || !voice) return;
    let closed = false, pending = false, failed = false, waiting = false;
    ready.current = false;
    setMix(stems ? 'loading' : 'original');
    applyGains.current();
    inst.pause(); voice.pause();
    if (!stems || !audioUrl) {
      inst.removeAttribute('src'); voice.removeAttribute('src');
      return;
    }
    const fail = () => {
      failed = true; ready.current = false;
      inst.pause(); voice.pause();
      applyGains.current();
      if (!closed) setMix('fallback');
    };
    const sync = () => {
      if (closed || failed) return;
      if (waiting || master.paused || master.ended || master.seeking || master.readyState < 2) {
        inst.pause(); voice.pause();
        return;
      }
      if (inst.readyState < 2 || voice.readyState < 2 || pending) return;
      try {
        for (const element of [inst, voice]) {
          element.playbackRate = master.playbackRate;
          if (Math.abs(element.currentTime-master.currentTime) > .06) element.currentTime = master.currentTime;
        }
        if (inst.paused || voice.paused) {
          pending = true;
          Promise.all([inst.play(), voice.play()]).then(() => {
            if (closed) { inst.pause(); voice.pause(); return; }
            ready.current = true; applyGains.current(); setMix('separated');
          }).catch(() => { if (!closed) fail(); }).finally(() => { pending = false; });
        }
      } catch { fail(); }
    };
    for (const [element, part] of [[inst, 'instrumental'], [voice, 'vocals']]) {
      element.src = audioUrl + '&part=' + part;
      element.addEventListener('canplay', sync);
      element.addEventListener('error', fail);
    }
    const stalled = () => { waiting = true; inst.pause(); voice.pause(); };
    const resumed = () => { waiting = false; sync(); };
    master.addEventListener('waiting', stalled);
    master.addEventListener('playing', resumed);
    master.addEventListener('canplay', resumed);
    const events = ['play', 'pause', 'seeking', 'seeked', 'ratechange', 'ended'];
    events.forEach(event => master.addEventListener(event, sync));
    const timer = setInterval(sync, 100);
    sync();
    return () => {
      closed = true; ready.current = false; applyGains.current();
      clearInterval(timer);
      events.forEach(event => master.removeEventListener(event, sync));
      master.removeEventListener('waiting', stalled);
      master.removeEventListener('playing', resumed);
      master.removeEventListener('canplay', resumed);
      for (const element of [inst, voice]) {
        element.removeEventListener('canplay', sync); element.removeEventListener('error', fail); element.pause();
      }
    };
  }, [stems, audioUrl, retry, audioRef, instrumentalRef, vocalRef]);
  return { graphRef, mix };
}

export function readEnergy(analyser, buffers) {
  if (!analyser) return { energy: 0, bass: 0 };
  analyser.getFloatTimeDomainData(buffers.wave);
  analyser.getByteFrequencyData(buffers.bins);
  let sum = 0;
  for (const sample of buffers.wave) sum += sample*sample;
  const energy = Math.min(1, Math.sqrt(sum/buffers.wave.length)*4);
  const bass = buffers.bins.slice(1, 5).reduce((a,b)=>a+b,0)/(4*255);
  return { energy, bass };
}

export function preparedEnergy(map, time) {
  if (!map?.step) return null;
  const index = Math.max(0, Math.floor(time/map.step));
  const sample = key => (map[key]?.[index] || 0)/100;
  const nextDrop = map.drops?.find(drop => drop >= time && drop-time < 1.5);
  return { energy: sample('instrumental'), vocals: sample('vocals'),
    tension: nextDrop === undefined ? 0 : 1-(nextDrop-time)/1.5,
    beat: Boolean(map.beats?.some(beat => Math.abs(beat-time) < .06)),
    drop: Boolean(map.drops?.some(drop => Math.abs(drop-time) < .12)) };
}
