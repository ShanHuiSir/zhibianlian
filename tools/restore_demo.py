"""Restore the original demo from small archival chunks, verifying its hash."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'docs' / 'demo' / 'demo-v1.0.mp4'
CHUNKS = ROOT / 'docs' / 'demo' / 'parts'
EXPECTED_SHA256 = '8c4ecf5828f676c32314e37067f31b52d40ffed8398cba39504d14838b7046f3'
EXPECTED_BYTES = 16457586


def restore():
    parts = [CHUNKS / f'demo-v1.0.mp4.part-a{letter}' for letter in 'abcdef']
    data = b''.join(part.read_bytes() for part in parts)
    if len(data) != EXPECTED_BYTES or hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Demo archive failed size or SHA-256 verification')
    if DESTINATION.exists():
        if hashlib.sha256(DESTINATION.read_bytes()).hexdigest() != EXPECTED_SHA256:
            raise FileExistsError('Existing demo differs; no file was overwritten')
    else:
        DESTINATION.write_bytes(data)
    print(f'Demo verified: {EXPECTED_BYTES} bytes, SHA-256 {EXPECTED_SHA256}')
    return DESTINATION


if __name__ == '__main__':
    restore()
