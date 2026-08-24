encrypted,SALT = (b'gAAAAABqbV0sSInlTZ-.........BTOA==', b'\x1aX\xe0\xa4\x15\x9f\xb8\x19L\x00\x87\x0c] \x07\r')
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path
from getpass import getpass
import base64, tempfile, runpy

def decrypt(password):
    kdf = Scrypt(
            salt=SALT,
            length=32,
            n=16384,
            r=8,
            p=1,
    )
    
    key = base64.urlsafe_b64encode(
        kdf.derive(password.encode('utf-8'))
    )

    f=Fernet(key)
    try:
        return f.decrypt(encrypted)
    except InvalidToken:
        return None

while 1:
    pwd = getpass("Password: ",echo_char="*")
    decrypted = decrypt(pwd)
    if decrypted: break
    print("Wrong password")

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "app.pvmz"
    print(path)
    path.write_bytes(decrypted)
    print()
    runpy.run_path(str(path))