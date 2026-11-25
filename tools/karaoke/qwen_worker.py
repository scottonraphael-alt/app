"""Independent Qwen song transcription and optional word-level forced alignment."""
import argparse
import json
import os
import re
from pathlib import Path

# Set this before importing torch so unsupported MPS kernels can fall back to CPU.
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')


LANGUAGES = {
    'en': 'English', 'it': 'Italian', 'ja': 'Japanese', 'zh': 'Chinese',
    'yue': 'Cantonese', 'fr': 'French', 'de': 'German', 'ko': 'Korean',
    'pt': 'Portuguese', 'ru': 'Russian', 'es': 'Spanish',
}
ALIGNER_LANGUAGES = {'zh', 'en', 'yue', 'fr', 'de', 'it', 'ja', 'ko', 'pt', 'ru', 'es'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('language')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()

    import torch
    from qwen_asr import Qwen3ASRModel

    use_mps = torch.backends.mps.is_available()
    device = 'mps' if use_mps else 'cpu'
    dtype = torch.float16 if use_mps else torch.float32
    options = {'dtype': dtype, 'device_map': device,
               'max_inference_batch_size': 1, 'max_new_tokens': 2048}
    language = LANGUAGES.get(args.language) or None
    with_aligner = args.language in ALIGNER_LANGUAGES
    if with_aligner:
        options.update(forced_aligner='Qwen/Qwen3-ForcedAligner-0.6B',
                       forced_aligner_kwargs={'dtype': dtype, 'device_map': device})
    try:
        model = Qwen3ASRModel.from_pretrained('Qwen/Qwen3-ASR-0.6B', **options)
        result = model.transcribe(audio=str(args.audio), language=language,
                                  return_time_stamps=with_aligner)[0]
    except Exception:
        if not use_mps:
            raise
        # Some Transformers/PyTorch builds cannot load or run this model on MPS.
        if 'model' in locals():
            del model
        if hasattr(torch, 'mps'):
            torch.mps.empty_cache()
        options['device_map'] = 'cpu'
        if with_aligner:
            options['forced_aligner_kwargs'] = {'dtype': torch.float32, 'device_map': 'cpu'}
        options['dtype'] = torch.float32
        model = Qwen3ASRModel.from_pretrained('Qwen/Qwen3-ASR-0.6B', **options)
        result = model.transcribe(audio=str(args.audio), language=language,
                                  return_time_stamps=with_aligner)[0]

    words = []
    for item in result.time_stamps or []:
        text = str(item.text)
        start, end = float(item.start_time), float(item.end_time)
        if text.strip() and 0 <= start < end:
            words.append({'word': text, 'start': start, 'end': end})
    if not words:
        # For languages without Qwen's aligner, retain transcript text as evidence.
        text = str(result.text).strip()
        pieces = re.findall(r"[\w']+|[^\w\s]", text, flags=re.UNICODE)
        words = [{'word': piece, 'start': None, 'end': None} for piece in pieces]
    payload = {'language': str(result.language), 'text': str(result.text),
               'segments': [{'words': words}] if words else []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
