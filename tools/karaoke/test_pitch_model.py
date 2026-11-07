"""Optional real-model check: run with the Mac preparation virtualenv."""
import unittest


class PitchModelTest(unittest.TestCase):
    def test_crepe_detects_a_known_note_without_filling_silence(self):
        try:
            import numpy as np
            import torch
            import torchcrepe  # noqa: F401
        except ImportError:
            self.skipTest('Installer les dépendances de préparation Mac pour ce test réel.')
        from prepare import extract_pitch
        torch.set_num_threads(4)
        sr = 16000
        tone = .2*np.sin(2*np.pi*440*np.arange(sr*2)/sr)
        audio = np.concatenate([np.zeros(sr), tone, np.zeros(sr)]).astype(np.float32)
        values = extract_pitch(audio, sr, 'crepe')
        self.assertTrue(all(value is None for value in values[:8]))
        self.assertTrue(all(value is None for value in values[-8:]))
        sung = [value for value in values[12:28] if value]
        self.assertGreaterEqual(len(sung), 14)
        self.assertLess(abs(1200*np.log2(np.median(sung)/440)), 35)


if __name__ == '__main__':
    unittest.main()
