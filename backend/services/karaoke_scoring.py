"""Server-owned rhythm and octave-invariant pitch scoring. No voice recordings."""
import math


def pitch_accuracy(sung, reference):
    if not sung or not reference or not all(math.isfinite(x) and x > 0 for x in (sung, reference)):
        return 0.0
    cents = abs(1200 * math.log2(sung / reference)) % 1200
    error = min(cents, 1200-cents)
    return max(0.0, 1-error/100)


def result(reference, samples, until, *, since=0):
    step = .1
    total = max(0, min(int(until/step), int(reference['duration']/step)))
    first = max(0, int(since/step))
    expected = set()
    for line in reference['lyrics']['lines']:
        for token in line['tokens']:
            expected.update(range(max(first, int(token['s']/step)), min(total, math.ceil(token['e']/step))))
    sung = {bin for bin, value in samples.items() if first <= bin < total and value['voiced']}
    hit = len(sung & expected)
    rhythm = round(100 * 2*hit/max(1, len(sung)+len(expected)))
    reference_pitch = reference.get('pitch', [])
    pitched = [(bin, reference_pitch[bin]) for bin in expected if bin < len(reference_pitch) and reference_pitch[bin]]
    pitch = None
    if pitched:
        pitch = round(100*sum(pitch_accuracy(samples.get(bin, {}).get('pitch'), hz) for bin, hz in pitched)/len(pitched))
    # 100 points per expected 100 ms of singing, shared equally between presence
    # and pitch when a reliable reference note exists. Silence never earns points.
    points = 0
    for bin in expected:
        value = samples.get(bin, {})
        if not value.get('voiced'):
            continue
        hz = reference_pitch[bin] if bin < len(reference_pitch) else 0
        points += 100 if not hz else 50 + round(50*pitch_accuracy(value.get('pitch'), hz))
    return {'points': points, 'points_max': len(expected)*100, 'rhythm': rhythm, 'pitch': pitch, 'score': rhythm if pitch is None else round(.5*rhythm+.5*pitch),
            'coverage': round(hit/max(1, len(expected)), 3), 'reference': 'aligned-vocals', 'frames': len(samples)}
