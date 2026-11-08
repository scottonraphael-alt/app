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
      const values = ready.current ? [0, clamp(level), clamp(voice)] : [clamp(level), 0, 0];
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
    let closed = false, failed = false, waiting = false, buffers = null, pair = null;
    const controller = new AbortController();
    ready.current = false;
    setMix(stems ? 'loading' : 'original');
    applyGains.current();
    inst.pause(); voice.pause();
    inst.removeAttribute('src'); voice.removeAttribute('src');
    if (!stems || !audioUrl) {
      inst.removeAttribute('src'); voice.removeAttribute('src');
      return;
    }
    const stopPair = () => {
      if (!pair) return;
      for (const source of pair.sources) {
        try { source.stop(); } catch { /* Already stopped. */ }
        source.disconnect();
      }
      pair = null;
    };
    const fail = () => {
      failed = true; ready.current = false;
      controller.abort();
      stopPair(); buffers = null;
      applyGains.current();
      if (!closed) setMix('fallback');
    };
    const sync = () => {
      if (closed || failed) return;
      if (waiting || master.paused || master.ended || master.seeking || master.readyState < 2) {
        stopPair();
        return;
      }
      const graph = graphRef.current;
      if (!buffers || !graph || graph.context.state !== 'running') return;
      try {
        const rate = master.playbackRate;
        const expected = pair ? pair.offset+(graph.context.currentTime-pair.at)*pair.rate : -1;
        if (!pair || pair.rate !== rate || Math.abs(expected-master.currentTime) > .08) {
          stopPair();
          // Both stems start at the exact same sample on one hardware clock.
          // JS timers only follow the room clock; they never synchronize stems.
          const at = graph.context.currentTime+.035, offset = master.currentTime+.035*rate;
          if (offset >= Math.min(...buffers.map(buffer => buffer.duration))) return;
          const sources = buffers.map((buffer, index) => {
            const source = graph.context.createBufferSource();
            source.buffer = buffer;
            source.playbackRate.value = rate;
            source.connect(graph.channels[index+1].analyser);
            return source;
          });
          pair = { sources, at, offset, rate };
          sources.forEach(source => source.start(at, offset));
          ready.current = true; applyGains.current(); setMix('separated');
        }
      } catch { fail(); }
    };
    const load = async () => {
      try {
        const graph = graphFor([master, inst, voice]);
        if (!graph) { fail(); return; }
        graphRef.current = graph; applyGains.current();
        const decoded = await Promise.all(['instrumental', 'vocals'].map(async part => {
          const response = await fetch(audioUrl+'&part='+part, {signal: controller.signal});
          if (!response.ok) throw new Error('Stem unavailable');
          const encoded = await response.arrayBuffer();
          if (closed) return null;
          return graph.context.decodeAudioData(encoded);
        }));
        if (closed) return;
        if (Math.abs(decoded[0].duration-decoded[1].duration) > .1) throw new Error('Stem duration mismatch');
        buffers = decoded; sync();
      } catch { if (!closed) fail(); }
    };
    const stalled = () => { waiting = true; stopPair(); };
    const resumed = () => { waiting = false; sync(); };
    master.addEventListener('waiting', stalled);
    master.addEventListener('playing', resumed);
    master.addEventListener('canplay', resumed);
    const events = ['play', 'pause', 'seeking', 'seeked', 'ratechange', 'ended', 'timeupdate'];
    events.forEach(event => master.addEventListener(event, sync));
    const timer = setInterval(sync, 100);
    load();
    return () => {
      closed = true; ready.current = false; applyGains.current();
      controller.abort(); stopPair(); buffers = null;
      clearInterval(timer);
      events.forEach(event => master.removeEventListener(event, sync));
      master.removeEventListener('waiting', stalled);
      master.removeEventListener('playing', resumed);
      master.removeEventListener('canplay', resumed);
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
