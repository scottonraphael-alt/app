"""Regression tests with synthetic audio only; no model loading or inference."""
import array
import hashlib
import logging
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

import soundfile as sf
from roformer_worker import separate_decoded


class ExportTests(unittest.TestCase):
    def source(self, folder):
        pcm = folder/'tone.wav'
        with wave.open(str(pcm), 'wb') as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(44100)
            frames = array.array('h', [int(3000*math.sin(i*2*math.pi*440/44100)) for i in range(44100) for _ in range(2)])
            writer.writeframes(frames.tobytes())
        mp3 = folder/'tone.mp3'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(pcm),'-c:a','libmp3lame',str(mp3)], check=True)
        return mp3

    def test_mp3_is_decoded_before_inference_and_real_writer_exports_float_wav(self):
        from audio_separator.separator.common_separator import CommonSeparator
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = self.source(folder)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            output = folder/'out'; output.mkdir()
            case = self
            class Separator:
                def load_model(self, model):
                    case.assertEqual(model, 'test-no-real-model')
                def separate(self, path, **kwargs):
                    info = sf.info(path)
                    case.assertEqual((info.format,info.subtype,info.samplerate,info.channels), ('WAV','FLOAT',44100,2))
                    audio, sr = sf.read(path, always_2d=True)
                    writer = CommonSeparator.__new__(CommonSeparator)
                    writer.logger = logging.getLogger('export-test')
                    writer.output_dir = str(output)
                    writer.sample_rate = sr
                    writer.input_subtype = info.subtype
                    writer.input_bit_depth = 32
                    writer.normalization_threshold = 1.
                    writer.amplification_threshold = 0.
                    for name in ('vocals.wav','instrumental.wav'):
                        writer.write_audio_soundfile(name, audio)
            separate_decoded(Separator(), source, output, 'test-no-real-model')
            for name in ('vocals.wav','instrumental.wav'):
                info = sf.info(output/name)
                self.assertEqual(info.subtype, 'FLOAT')
                self.assertLess(abs(info.duration-1), .02)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            self.assertFalse(list(output.glob('.decoded-*')))

    def test_swallowed_export_error_is_not_treated_as_a_valid_stem(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = self.source(folder)
            output = folder/'out'; output.mkdir()
            class Separator:
                def load_model(self, model): pass
                def separate(self, path, **kwargs):
                    (output/'vocals.wav').write_bytes(b'not a WAV')
                    (output/'instrumental.wav').write_bytes(b'')
            with self.assertRaisesRegex(RuntimeError, 'Export RoFormer invalide'):
                separate_decoded(Separator(), source, output, 'test')


if __name__ == '__main__':
    unittest.main()
