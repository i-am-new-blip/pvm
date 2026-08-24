from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from mypvm.mypvm._filebundler import bundlefiles as bundle
from cryptography.fernet import Fernet, InvalidToken
from mypvm.mypvm import VM, __spec__, needs
from argparse import ArgumentParser
from ast import literal_eval, unparse
from getpass import getpass
from pathlib import Path
from json import dumps
import os, base64
import zipfile

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1

PVM_ROOT = Path(__spec__.submodule_search_locations[0])
PRP = PVM_ROOT.parent
print(PVM_ROOT, PRP)
def pvm_to_py(txt):
    
    json = VM.bytecode(txt)

    return f"""import mypvm
vm = mypvm.VM()
vm.load({dumps(json)})
vm.run()"""


def bundle_py_files(in_path: Path):
    py_files = sorted(in_path.glob("*.py"))

    module_names = [p.stem for p in py_files]
    bundmap = {
        name: i
        for i, name in enumerate([*module_names, "main"])
    }

    contents = [p.read_text() for p in py_files]
    contents.append(
        pvm_to_py(in_path / "__main__.pvm")
    )

    wrapper, dg, order = bundle(bundmap, contents)
    return f"{unparse(wrapper)} # {dg}, top order: {order}"


def make_archive(in_path: Path, out_file: Path, just_required: bool):
    make_archive_VERSION = 2
    
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # mypvm/
        if not just_required:
            for path in PVM_ROOT.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    z.write(path, path.relative_to(PRP))
        else:
            for path in PVM_ROOT.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and (path.stem in needs or str(path) in needs):
                    z.write(path, path.relative_to(PRP))
            z.write(PVM_ROOT / '__init__.py',Path("mypvm/__init__.py"))
        # __main__.py
        z.writestr("__main__.py", bundle_py_files(in_path))
        
        # version.txt
        z.writestr("version.txt", f'PVMZ/{make_archive_VERSION}')
        
        # assets/
        for path in in_path.rglob("*"):
            if path.is_file() and path.name != "__main__.pvm" and '.py' != path.suffix:
                z.write(path, Path("assets") / path.relative_to(in_path))

def password_to_key(password,salt=None):
    if salt is None: salt = os.urandom(16)

    kdf = Scrypt(
        salt=salt,
        length=32,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )

    return base64.urlsafe_b64encode(
        kdf.derive(password)
    ), salt

mainhead = "encrypted,SALT = "

def encrypt_archive(in_path, password, out_file):
    def get_main(encrypted, salt):
        return f'''{mainhead}({encrypted!r}, {salt!r})
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path
from getpass import getpass
import base64, tempfile, runpy

def decrypt(password):
    kdf = Scrypt(
            salt=SALT,
            length=32,
            n={SCRYPT_N},
            r={SCRYPT_R},
            p={SCRYPT_P},
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
    runpy.run_path(str(path))'''
    
    encrypt_archive_VERSION = 2

    key, salt = password_to_key(password) # makes password an fernet key
    
    f = Fernet(key)
    
    with open(in_path,'rb') as file:
        read = file.read()

    encrypted = f.encrypt(read)

    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("version.txt", f'PVMZE/{encrypt_archive_VERSION}')
        z.writestr("__main__.py", get_main(encrypted, salt))
        
def decrypt_archive(in_path, out_file, password = None):
    with zipfile.ZipFile(in_path) as z:
        splitlines = z.read("__main__.py").decode('utf-8').splitlines()
        if not splitlines[0].startswith(mainhead):
            raise ValueError("Invalid PVMZE header")
        encrypted, salt = literal_eval(splitlines[0][len(mainhead):])
        
    def decrypt(password):
        key, _ = password_to_key(password, salt)

        f=Fernet(key)
        try:
            return f.decrypt(encrypted)
        except InvalidToken:
            return None

    if password is None:
        while 1:
            pwd = getpass("Password: ",echo_char="*").encode('utf-8')
            decrypted = decrypt(pwd)
            if decrypted: break
            print("Wrong password")
    else:
        decrypted = decrypt(password)
        if not decrypted:
            print("Wrong password")
            return 0
        
    with open(out_file,'wb') as f:
        f.write(decrypted)