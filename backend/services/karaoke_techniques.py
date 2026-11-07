"""Conservative, indicative technique counts from an opted-in 20 Hz pitch stream.

No recording, no effect on the score. A short pitch history stays in memory.
"""
import math


def observe(state, position, pitch, voiced):
    if not voiced or not pitch or not math.isfinite(pitch) or not 50 <= pitch <= 1500:
        state['history'] = []
        return
    history = state.setdefault('history', [])
    cents = 1200*math.log2(pitch/440)
    if history and (position <= history[-1][0] or position-history[-1][0] > .2):
        history.clear()
    history.append((position, cents))
    del history[:-64]
    state['available'] = True
    state.setdefault('vibrato', 0)
    state.setdefault('glissando', 0)
    wave = [(t, p) for t, p in history if t >= position-1.1]
    if len(wave) >= 18 and wave[-1][0]-wave[0][0] >= .85:
        span = wave[-1][0]-wave[0][0]
        values = [p for _, p in wave]
        differences = [b-a for a, b in zip(values, values[1:])]
        signs = [1 if value > 4 else -1 for value in differences if abs(value) > 4]
        turns = sum(a != b for a, b in zip(signs, signs[1:]))
        rate = turns/(2*span)
        if 4 <= rate <= 8 and 35 <= max(values)-min(values) <= 250 and abs(values[-1]-values[0]) <= 120:
            if position > state.get('vibrato_until', -1):
                state['vibrato'] += 1
            state['vibrato_until'] = position+.4
    glide = [(t, p) for t, p in history if t >= position-.45]
    if len(glide) >= 7 and glide[-1][0]-glide[0][0] >= .28:
        values = [p for _, p in glide]
        delta = values[-1]-values[0]
        differences = [b-a for a, b in zip(values, values[1:]) if abs(b-a) > 3]
        aligned = sum(value*delta > 0 for value in differences)
        if 110 <= abs(delta) <= 700 and len(differences) >= 5 and aligned/len(differences) >= .85:
            if position > state.get('glissando_until', -1):
                state['glissando'] += 1
            state['glissando_until'] = position+.5


def summary(state):
    if not state or not state.get('available'):
        return None
    return {'vibrato': state.get('vibrato', 0), 'glissando': state.get('glissando', 0), 'indicative': True}
