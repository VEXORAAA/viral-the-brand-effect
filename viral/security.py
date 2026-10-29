"""Credenciales scrypt y tokens aleatorios; nunca contienen la identidad del usuario."""
import hashlib
import hmac
import secrets


def hash_secret(secret):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f'scrypt${salt.hex()}${digest.hex()}'


def verify_secret(secret, stored):
    try:
        alg, salt, expected = stored.split('$')
        if alg != 'scrypt' or not isinstance(secret, str) or len(secret) > 256:
            return False
        actual = hashlib.scrypt(secret.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def token_digest(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def new_pins():
    pins = set()
    while len(pins) < 7:
        pins.add(f'{secrets.randbelow(10000):04}')
    return dict(zip(map(str, range(7)), sorted(pins)))


def valid_pins(pins):
    return (isinstance(pins, dict) and set(pins) == set(map(str, range(7)))
            and all(isinstance(p, str) and p.isascii() and p.isdigit() and len(p) == 4 for p in pins.values())
            and len(set(pins.values())) == 7)
