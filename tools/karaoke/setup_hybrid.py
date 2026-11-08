#!/usr/bin/env python3
"""Install optional Mac tools; never starts a song preparation."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse
import zipfile

ROOT = Path(__file__).resolve().parents[2]
COMMIT = '7b210ca36ff5a2b79187fb1727af58fc977cc301'
MODEL_SHA = '36595b2746f0d1183346fd448c7b99df9d7c51fd403bc45025438c3ebf439396'


def run(argv):
    subprocess.run([str(v) for v in argv], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='https://api.loasis.app')
    args = parser.parse_args()
    parsed = urlparse(args.api_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c in args.api_url for c in '\n\r'):
        parser.error('Utiliser l’URL HTTPS de l’API, sans identifiants ni paramètres.')
    tools = ROOT/'.karaoke-tools'
    tools.mkdir(exist_ok=True)
    repo = tools/'TIFA'
    if not repo.exists():
        run(['git', 'clone', '--filter=blob:none', '--no-checkout', 'https://github.com/openvpi/TIFA.git', repo])
        run(['git', '-C', repo, 'fetch', '--depth', '1', 'origin', COMMIT])
        run(['git', '-C', repo, 'checkout', '--detach', COMMIT])
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT:
        raise ValueError('Le checkout TIFA diffère de la version validée ; conserver ses modifications avant de le réinstaller.')
    for name in ('roformer', 'tifa'):
        env = ROOT/f'.venv-karaoke-{name}'
        if not (env/'bin/python').is_file():
            run([sys.executable, '-m', 'venv', env])
        command = [env/'bin/python', '-m', 'pip', 'install', '-r', ROOT/f'tools/karaoke/requirements.{name}.txt']
        if name == 'tifa':
            command.extend(['-r', repo/'requirements.txt'])
        run(command)
    archive = tools/'TIFA-1.0.zip'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != MODEL_SHA:
        pending = tools/'TIFA-1.0.zip.tmp'
        urllib.request.urlretrieve('https://github.com/openvpi/TIFA/releases/download/v1.0.0/TIFA-1.0.zip', pending)
        if hashlib.sha256(pending.read_bytes()).hexdigest() != MODEL_SHA:
            pending.unlink()
            raise ValueError('Empreinte du modèle TIFA incorrecte.')
        os.replace(pending, archive)
    models = tools/'models'
    models.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        if any(not (models/member.filename).resolve().is_relative_to(models.resolve()) for member in package.infolist()):
            raise ValueError('Archive de modèle invalide.')
        package.extractall(models)
    # Generate a relay-only credential, never copy the Anthropic or session key.
    config = ROOT/'.env.karaoke-hybrid'
    try:
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write('\nIRIS_KARAOKE_API_URL='+shlex.quote(args.api_url.rstrip('/'))+'\nKARAOKE_PREPARATION_SECRET='+secrets.token_hex(32)+'\n')
    except FileExistsError:
        pass
    print('Installation terminée. Aucune chanson lancée.')
    print('Configuration privée conservée dans .env.karaoke-hybrid ; installer le même secret sur le VPS.')


if __name__ == '__main__':
    main()
