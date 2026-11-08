"""Optional Mac-only MMS CTC alignment; no Whisper timestamps are reused.

The multilingual model uses romanized text. Explicit frame times avoid drift
when inferring bounded overlapping chunks of a long song on CPU.
"""
import re
import unicodedata


def units(text, language):
    if language == 'ja':
        # Already phonetic kana supplied by build_plan, including sung overrides.
        from services.karaoke_phonetics import morae
        result = []
        for part in morae(text):
            if not part.strip():
                continue
            sound = romanize(part)
            if sound:
                result.append((part, sound))
            elif result:
                original, previous = result[-1]
                result[-1] = (original+part, previous)
            else:
                raise ValueError('Ponctuation initiale non alignable en MMS ; utiliser Whisper.')
        return result
    from anyascii import anyascii
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*|[^\w\s]", text, re.UNICODE)
    result, prefix = [], ''
    for word in words:
        phonetic = re.sub("[^a-z']", '', anyascii(word).lower())
        if phonetic:
            result.append((prefix+word, phonetic))
            prefix = ''
        elif result:
            original, normalized = result[-1]
            result[-1] = (original+word, normalized)
        else:
            prefix += word
    return result


def romanize(text):
    from services.karaoke_text import _kakasi
    from anyascii import anyascii
    text = ''.join(p['hepburn'] for p in _kakasi().convert(text))
    return re.sub("[^a-z']", '', anyascii(unicodedata.normalize('NFKC', text)).lower())


def emissions(model, audio, torch, sr=16000, chunk_seconds=15, context_seconds=1):
    values, bounds = [], []
    hop, context = round(sr*chunk_seconds), round(sr*context_seconds)
    for center in range(0, len(audio), hop):
        start, end = max(0, center-context), min(len(audio), center+hop+context)
        with torch.inference_mode():
            matrix, _ = model(torch.from_numpy(audio[start:end]).unsqueeze(0))
        # Wav2Vec2: receptive field 400 samples, stride 320 at 16kHz.
        centers = start/sr + (torch.arange(matrix.shape[1]) * 320 + 200)/sr
        mask = (centers >= center/sr) & (centers < min(len(audio), center+hop)/sr)
        values.append(matrix[0, mask].cpu())
        bounds.extend((round(max(0., start/sr+(int(i)*320+40)/sr), 6),
                       round(min(len(audio)/sr, start/sr+(int(i)*320+360)/sr), 6))
                      for i in torch.arange(matrix.shape[1])[mask])
        print(f'  MMS : analyse vocale {min(center+hop, len(audio))/sr:.0f}/{len(audio)/sr:.0f} s', flush=True)
    return torch.cat(values), bounds


def align_mms(vocals, lines, language):
    import librosa
    import torch
    from torchaudio.pipelines import MMS_FA
    print('  MMS CTC : chargement du modèle multilingue sur CPU…', flush=True)
    model = MMS_FA.get_model().eval()
    audio, sr = librosa.load(str(vocals), sr=MMS_FA.sample_rate, mono=True)
    matrix, times = emissions(model, audio, torch, sr)
    del model
    tokenizer, aligner = MMS_FA.get_tokenizer(), MMS_FA.get_aligner()
    groups = [units(text, language) for text in lines if text.strip()]
    if not groups or any(not group or any(not sound for _, sound in group) for group in groups):
        raise ValueError('Texte non pris en charge par la normalisation MMS ; utiliser --aligner whisper.')
    # Wildcards absorb nontranscribed intros, interjections and instrumental gaps.
    # They cannot fix a missing reference word: low-scoring spans remain flagged.
    target, locations = ['*'], []
    for group in groups:
        locations.append([])
        for original, sound in group:
            locations[-1].append(len(target))
            target.append(sound)
        target.append('*')
    with torch.inference_mode():
        spans = aligner(matrix, tokenizer(target))
    if len(spans) != len(target):
        raise ValueError('Alignement MMS incomplet ; aucune estimation silencieuse.')
    segments = []
    for group, positions in zip(groups, locations):
        words = []
        for (original, _), position in zip(group, positions):
            parts = spans[position]
            if not parts:
                raise ValueError('Un bloc MMS ne dispose pas de position acoustique.')
            start, end = parts[0].start, parts[-1].end
            score = sum(float(p.score)*(p.end-p.start) for p in parts)/max(1, end-start)
            words.append({'word': ('' if language == 'ja' or not words else ' ')+original,
                          'start': round(times[start][0], 3), 'end': round(times[end-1][1], 3),
                          'probability': score})
        segments.append({'text': ''.join(w['word'] for w in words), 'start': words[0]['start'],
                         'end': words[-1]['end'], 'words': words})
    return {'language': language, 'segments': segments}
