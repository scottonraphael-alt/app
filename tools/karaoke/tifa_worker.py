"""Pinned upstream TIFA API, CPU-only, JSON export without fabricated spans."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    import torch
    import lightning.pytorch as pl
    from inference.api import load_inference_model
    from inference.data import AudioTextDataset
    from inference.module import ForcedAlignmentInferenceModule
    from lib.config.schema import ConfigurationScope
    job = json.loads(args.job.read_text())
    torch.set_num_threads(job.get('threads', 4))
    backend, vocabulary, config = load_inference_model(args.model, scope=ConfigurationScope.FA)
    dataset = AudioTextDataset(filemap={item['id']: Path(item['audio']) for item in job['items']},
        g2p_config=config.g2p, g2p_root=args.model.parent, vocabulary=vocabulary,
        audio_sample_rate=backend.sample_rate, language=[job['language']], oov_handling='raise')
    outputs = {}
    class Export(pl.callbacks.Callback):
        def on_predict_batch_end(self, trainer, module, results, batch, *unused, **kwargs):
            for result in results:
                outputs[result['identifier']] = {
                    'texts': result['texts'], 'word_ids': result['words'].tolist(),
                    'spans': [[round(float(s)*backend.timestep, 6), round(float(e)*backend.timestep, 6)]
                              for s, e in result['spans'].tolist()],
                    'phonemes': result['phonemes'],
                    'pronunciations': result['group_scripts']}
    module = ForcedAlignmentInferenceModule(backend, score_unit='levenshtein', skip_penalty=.5)
    loader = torch.utils.data.DataLoader(dataset, batch_size=1, num_workers=0, collate_fn=dataset.collate)
    trainer = pl.Trainer(accelerator='cpu', devices=1, precision='32-true', logger=False,
                         enable_checkpointing=False, callbacks=[Export()])
    trainer.predict(module, loader)
    if set(outputs) != {item['id'] for item in job['items']}:
        raise ValueError('TIFA a ignoré une phrase ; consulter le journal.')
    Path(job['output']).write_text(json.dumps(outputs, ensure_ascii=False))


if __name__ == '__main__':
    main()
