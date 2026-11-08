"""Run only in the isolated RoFormer environment."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    os.environ['OMP_NUM_THREADS'] = str(args.threads)
    import torch
    torch.set_num_threads(args.threads)
    # CPU is deliberate here; legacy MPS spectral kernels differ by macOS.
    torch.backends.mps.is_available = lambda: False
    from audio_separator.separator import Separator
    args.output.mkdir(parents=True, exist_ok=True)
    separator = Separator(model_file_dir=str(args.models), output_dir=str(args.output),
                          output_format='WAV', use_soundfile=True,
                          normalization_threshold=1., amplification_threshold=0.,
                          mdxc_params={'segment_size': 256, 'override_model_segment_size': False,
                                       'batch_size': 1, 'overlap': 8, 'pitch_shift': 0})
    separate_decoded(separator, args.source, args.output, args.model)


def separate_decoded(separator, source, output, model):
    """Normalize the decoder and WAV subtype before expensive inference.

    Audio Separator 0.40 copies sf.info(MP3).subtype ('MPEG_LAYER_III')
    to its WAV writer and swallows that writer's exception. A lossless float
    WAV avoids that bug and MP3-decoder-dependent duration differences.
    """
    import soundfile as sf
    with tempfile.TemporaryDirectory(prefix='.decoded-', dir=output) as temporary:
        decoded = Path(temporary)/'input.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:a:0',
            '-vn', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_f32le', str(decoded)], check=True, timeout=300)
        reference = sf.info(decoded)
        if reference.format != 'WAV' or reference.subtype != 'FLOAT' or reference.frames <= 0:
            raise RuntimeError('Le décodage WAV de l’original a échoué avant RoFormer.')
        separator.load_model(model)
        separator.separate(str(decoded), custom_output_names={'Vocals': 'vocals', 'Instrumental': 'instrumental'})
        for name in ('vocals.wav', 'instrumental.wav'):
            path = Path(output)/name
            try:
                if path.is_symlink():
                    raise ValueError('Lien symbolique interdit.')
                actual = sf.info(path)
                valid = actual.format == 'WAV' and actual.subtype in ('FLOAT', 'PCM_16', 'PCM_24', 'PCM_32') \
                    and actual.samplerate == reference.samplerate and actual.channels == reference.channels \
                    and actual.frames > 0 and abs(actual.frames-reference.frames) <= round(.02*reference.samplerate)
            except (OSError, RuntimeError, ValueError):
                valid = False
            if not valid:
                raise RuntimeError(f'Export RoFormer invalide : {name}. Les pistes doivent être des WAV lisibles de même durée que l’entrée.')



if __name__ == '__main__':
    main()
