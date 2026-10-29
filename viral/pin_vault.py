"""PIN de empresa cifrados; solo el servicio administrativo puede recuperarlos."""
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .engine import RuleError

class PinVault:
    def __init__(self, store, key=None):
        if not key:
            if store.postgres:
                raise RuleError('Configura VIRAL_PIN_ENCRYPTION_KEY para consultar los PIN desde Administración.')
            keyfile = Path(store.path).with_suffix('.pin.key')
            # La creación es exclusiva; dos arranques nunca sobrescriben la clave.
            try:
                descriptor = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = keyfile.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(key)
        try:
            self.cipher = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise RuleError('VIRAL_PIN_ENCRYPTION_KEY debe ser una clave Fernet válida.') from exc

    def encrypt(self, game_id, pins):
        payload = json.dumps({'game_id': game_id, 'pins': pins}, sort_keys=True).encode()
        return self.cipher.encrypt(payload).decode('ascii')

    def decrypt(self, game_id, ciphertext):
        try:
            payload = json.loads(self.cipher.decrypt(ciphertext.encode('ascii')))
            if payload['game_id'] != game_id:
                raise ValueError('Partida distinta')
            return payload['pins']
        except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise RuleError('No se pueden recuperar estos PIN con la clave actual. Puedes generar nuevos PIN sin perder el avance.') from exc
