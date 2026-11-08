"""Run only in the isolated RoFormer environment."""
import argparse
import os
from pathlib import Path


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
    separator.load_model(args.model)
    separator.separate(str(args.source), custom_output_names={'Vocals': 'vocals', 'Instrumental': 'instrumental'})
    if not (args.output/'vocals.wav').is_file() or not (args.output/'instrumental.wav').is_file():
        raise RuntimeError('RoFormer n’a pas produit les deux pistes attendues.')


if __name__ == '__main__':
    main()
