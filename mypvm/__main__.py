#!/usr/bin/env python3.14
from mypvm.mypvm._packer import make_archive, encrypt_archive, decrypt_archive
from mypvm.mypvm import VM, VMError
from mypvm.mypvm._emitter import PythonEmitter
from mypvm.mypvm._assembler import Assembler
import argparse, sys, os, json, getpass
from pathlib import Path

def main():
    
    parser = argparse.ArgumentParser("pvm")

    sub = parser.add_subparsers(dest="cmd")

    runp = sub.add_parser("run")
    runp.add_argument("file")
    runp.add_argument("pargs",nargs=argparse.REMAINDER)

    asmp = sub.add_parser("asm")
    asmp.add_argument("file")

    disp = sub.add_parser("dis")
    disp.add_argument("file")
    
    jitp = sub.add_parser("jit")
    jitp.add_argument("file")
    jitp.add_argument("pargs",nargs=argparse.REMAINDER)
    
    emitp = sub.add_parser("emit")
    emitp.add_argument("file")
    emitp.add_argument("output")
    emitp.add_argument("--standalone",action="store_true")
    
    packp = sub.add_parser("pack")
    packp.add_argument("infolder", type=Path, help="Input project folder")
    packp.add_argument("outfile", type=Path, help="Output .pvmz file")
    packp.add_argument("--just-required",action="store_true",help="Get the only required files, as marked in __init__")
    
    encryptp = sub.add_parser("encrypt")
    encryptp.add_argument("infile", type=Path, help="Input .pvmz file")
    encryptp.add_argument("outfile", help="The output .pvmze")
    encryptp.add_argument("password", type=(lambda a: a.encode('utf-8')), nargs="?", help="Password to use in the fernet encryption")
    
    decryptp = sub.add_parser("decrypt")
    decryptp.add_argument("infile", type=Path, help="Input .pvmze file")
    decryptp.add_argument("outfile", help="The output .pvmz")
    decryptp.add_argument("password", type=(lambda a: a.encode('utf-8')), nargs="?", help="Password to use in the fernet decryption")
    
    instructionsp = sub.add_parser("instructions")
    
    if len(sys.argv) > 1 and sys.argv[1] not in sub.choices.keys() and sys.argv[1] not in ["-h", "--help"]:
        sys.argv.insert(1, "run")
    
    args = parser.parse_args()
    vm = VM()    
    asm = Assembler(vm)
    emitter = PythonEmitter(vm)
    
    '''All PVM programs will have the command line like this:
    run|jit
    source.pvm|py (py for python running emitted, pvm for normally)
    *other args'''
    
    match args.cmd:
        
        case "run":
            sys.argv = ['run', args.file, *args.pargs]
            bytecode = VM.bytecode(args.file)
            vm.load(bytecode)
            try:
                vm.run()
            except VMError as e:
                print(e)
                if vm.debugsettings['ask-pdb-on-err']:
                    w = input("run debugger? [y/n] ")
                    if w == "y":
                        breakpoint()
                sys.exit(1)
        case "asm":

            with open(args.file) as f:
                code = f.read()

            print(json.dumps(asm.assemble(code)))
        case "dis":            
            bytecode = VM.bytecode(args.file)
            print(asm.disassemble(bytecode))
        case "jit":
            sys.argv = ['jit', args.file, *args.pargs]
            bytecode = VM.bytecode(args.file)
            generated = emitter.emit(bytecode)
            code = compile(generated, f"<jit:{os.path.basename(args.file)}>", "exec")
            exec(code,{"__PVM_JIT__": True})
        case "emit":
            bytecode = VM.bytecode(args.file)
            generated = emitter.emit(bytecode)
            output = args.output
            standalone = args.standalone
            if not standalone:
                with open(output,'w') as f:
                    f.write(generated) 
        case "instructions":
            i=vm.intructs
            print({i: v.__name__ for i,v in i.items()})
            
        case "pack":
            make_archive(args.infolder, args.outfile, args.just_required)
        case "encrypt":
            if args.password is not None:
                password = args.password
            else:
                while 1:
                    pw = getpass.getpass("Password: ",echo_char="*")
                    if pw == "":
                        print("Password cant be empty.")
                        continue
                    if pw == getpass.getpass("Repeat password: ",echo_char="*"):
                        break
                    print('Passwords dont match.')
                password = pw.encode('utf-8')
            
            encrypt_archive(args.infile, password, args.outfile)
        case "decrypt":
            decrypt_archive(args.infile, args.outfile, args.password)
            
if __name__ == '__main__': main()