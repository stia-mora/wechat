"""Create separate monitor credentials locally; never print secrets or overwrite files."""
import argparse
import hashlib
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env-file', required=True, type=Path)
parser.add_argument('--credentials-file', required=True, type=Path)
args = parser.parse_args()
if args.env_file.exists() or args.credentials_file.exists():
    parser.error('Output already exists; keep it or choose a new explicit path')
password = secrets.token_urlsafe(24)
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 180000).hex()
key = secrets.token_hex(32)
with args.env_file.open('x', encoding='ascii') as stream:
    stream.write(f'TRAFFIC_PASSWORD_HASH={salt.hex()}:{digest}\nTRAFFIC_SESSION_KEY={key}\n')
with args.credentials_file.open('x', encoding='utf-8') as stream:
    stream.write('WeChat Source 独立流量监控\nURL: https://wechat.aim888888.xyz/traffic\nUsername: admin\nPassword: ' + password + '\n')
print('Created credential files without printing secret values.')
