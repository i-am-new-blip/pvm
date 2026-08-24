from mypvm.mypvm import VM

class PythonEmitter:
    def __init__(self, vm=None):
        self.vm = vm if vm else VM()
    
    def emit_line(self, opc: int, args: list|None = None):
            def assemble_convert(a,b=None, forconverted=None):
                if b is not None:
                    return assemble_convert(a), assemble_convert(b)
                if type(a)==list and len(a)==1:
                    if not forconverted:
                        return f"self.register[{a[0]}]"
                    else: 
                        return f"{forconverted}(self.register[{a[0]}])"
                return repr(a)
            
            def emit(addr,expr,op='='):
                return f'self.register[{addr}] {op} {expr}\nself.pc += 1'
            
            match opc:
                case 0:
                    opr, a, b, addr = args
                    a,b = assemble_convert(a,b)
                    
                    if not(0 <= opr < len(self.vm.math_opr)): 
                        raise TypeError(f"{opr} must be 0-{len(self.vm.math_opr)-1}")
                    
                    opr = self.vm.math_opr[opr]
                    
                    if opr == "+u":
                        expr = f'+{a}'
                    elif opr == "-u":
                        expr = f'-{a}'
                    else:
                        expr = f'{a} {opr} {b}'
                        
                    return emit(addr,expr)
                case 1:
                    opr, a, b, addr = args
                    a,b = assemble_convert(a,b)
                    
                    if not(0 <= opr < len(self.vm.comp_opr)):
                        raise TypeError(f"{opr} must be 0-{len(self.vm.comp_opr)-1}")
                    
                    opr = self.vm.comp_opr[opr]
                    
                    return emit(addr,f'{a} {opr} {b}')
                case 2:
                    opr, a, b, addr = args
                    a,b = assemble_convert(a,b)
                    
                    if not (0 <= opr < len(self.vm.bin_opr)):
                        raise TypeError(f"{opr} must be 0-{len(self.vm.bin_opr)-1}")
                    
                    opr = self.vm.bin_opr[opr]
                    
                    if opr == 'not':
                        expr = f'not {a}'
                    elif opr == 'or':
                        expr = f"{a} or {b}"
                    # no else because any other INVALID fall on the raise
                    return emit(addr,expr)
                case 3:
                    *args, addr = args
                    args = " + ".join(map(lambda a:assemble_convert(a,None,'str'), args))
                    return emit(addr, args, "+=")
                case 4:
                    name,addr = args
                    return emit(addr, name) # its a builtin so...
                case 5:
                    fromAddr, argc, *rest = args
                    
                    # Max optimization: Extract target directly from the remainder slice
                    toAddr = rest[argc] if len(rest) > argc else None
                    
                    call = f'self.register[{fromAddr}]({", ".join(assemble_convert(x) for x in rest[:argc])})'
                    if toAddr is not None:
                        call = f'self.register[{toAddr}] = {call}'
                        
                    return call + '\nself.pc += 1'
                case 6: 
                    startingAddr, *things, addr = args
                    expr=f'self.register[{startingAddr}]'
                    for i in things:
                        expr += f'.{i}'
                    return emit(addr, expr)
                case 7:
                    addr, index, outaddr = args
                    index = assemble_convert(index)
                    return emit(outaddr,f'self.register[{addr!r}][{index}]')
                case 8:
                    v,addr = args
                    return emit(addr,repr(v))
                case 9:
                    if not args:
                        return "self.running = False\nif self.debugsettings['register-print']:pprint(self.register)"
                    else:
                        return f"self.running = False\nself.returns = {assemble_convert(args[0])}\nif self.debugsettings['register-print']:pprint(self.register)"
                case 10:
                    label = args
                    if len(label) == 2:
                        label, goto = label
                        e = f'= {goto!r}'
                    else: 
                        label, = label
                        e = f'+= 1'
                    
                    return f'self.labels[{label!r}]=self.pc+1\nself.pc {e}'
                case 18:
                    if not args: return "self.pc+=1"
                    return f"fargs=self.callstack[-1][1]\nargs={args!r}\nfor i,v in zip(args,map(self.convert,fargs)):self.register[i]=v\nself.callstack[-1][3]=args\nself.pc+=1"
                case 19:
                    v,addr = args
                    return emit(addr,f'self.heap[{v!r}]')
                case 11:
                    addr, = args
                    return ((f"addrn = {addr}" if isinstance(addr,int) else f"self.labels[{addr!r}]\n")+
                            f"\nif self.debugsettings['printin']['FGOTO']: print(f'jumping (f_goto) from {{self.pc}} to {addr} ({{addrn}})')\nself.pc=addrn")
                case 12:
                    addr = args
                    if len(addr) == 3:
                        addr, args, returnvaladdr = addr
                    elif len(addr) == 2:
                        addr, args = addr
                        returnvaladdr = None
                    else:
                        addr, = addr
                        args = None
                        returnvaladdr = None
                        
                    # Max optimization: Pre-transpile the argument array contents right here
                    if args:
                        args_compiled = f"[{', '.join(assemble_convert(x) for x in args)}]"
                    else:
                        args_compiled = "None"
                        
                    target = f"{addr}" if isinstance(addr, int) else f"self.labels[{addr!r}]"
                        
                    return (f"self.callstack.append([self.pc + 1,{args_compiled},{returnvaladdr!r}, None])\n"
                    f"newaddr = {target}"
                    '\nif self.code[self.idx][newaddr][0] != 18: raise RuntimeError("Every function must start with C_INITFUNC (opc number 18)")'
                    f"\nif self.debugsettings['printin']['FCALL']: print(f'jumping (f_call) from {{self.pc}} to {addr} ({{newaddr}})')"
                    "\nself.pc=newaddr")
                case 13:
                    if args:
                        returns, = args
                        line1 = f"if returning:self.register[returning]=self.register[{returns}];self.register.pop({returns})\n"
                        line2 = 'else: raise TypeError("Mismatch in function requests.")\n'
                    else:
                        line1 = ""
                        line2 = 'if returning != None:raise TypeError("Mismatch in function requests.")\n'
                    return ("if not self.callstack: raise RuntimeError('callstack empty')\npc,_,returning,delete = self.callstack.pop()"+
                    line1+line2+
                    "if delete: self.register.pop(delete)\n"+
                    "if self.debugsettings['printin']['FRET']: print(f'jumping (f_ret) from {self.pc} to {pc}')\nself.pc = pc")
                case 14:
                    binOpAddr, addr = args
                    return (f"if not self.register.get({binOpAddr}): self.pc+=1; continue\n"
                    f"pc = self.labels.get({addr},{addr})\n"
                    "if self.debugsettings['printin']['FIF']: print(f'jumping (f_if) from {self.pc} to {pc}')\n"
                    "self.pc=pc")
                case 15:
                    text,addr = args
                    return emit(addr,f"input({text!r})")
                case 16:
                    addr, = args
                    return f'print({assemble_convert(addr)});self.pc+=1'
                case 17:
                    if len(args) == 2:
                        sr: list | int | str = args[0]
                        er: int = args[1]
                    else:
                        sr: list | int | str = args[0]
                        er: None = None
                    
                    # "if self.debugsettings['printin']['FCLEAR']: print(...)"
                    if type(sr)==list:
                        return '\n'.join(f'self.register.pop({i!r})\nif self.debugsettings["printin"]["FCLEAR"]: print(f"deleting addr {i!r}, from pc {{self.pc}}")' for i in sr) + "\nself.pc+=1"
                    elif type(sr) == int:
                        
                        if er!=None:
                            return '\n'.join(f'self.register.pop({i!r})\nif self.debugsettings["printin"]["FCLEAR"]: print(f"deleting addr {i!r}, from pc {{self.pc}}")' for i in range(sr,er+1)) + "\nself.pc+=1"
                        else:
                            return f'self.register.pop({sr})\nif self.debugsettings["printin"]["FCLEAR"]: print(f"deleting addr {sr}, from pc {{self.pc}}")\nself.pc+=1'
                    else:
                        return f'self.register.pop({sr!r})\nif self.debugsettings["printin"]["FCLEAR"]: print(f"deleting addr {sr!r}, from pc {{self.pc}}")\nself.pc+=1'
                case 20:
                    bindingname, heapid = args
                    return f"if 'C_DEFINE' not in self.capabilities : raise PermissionError(\"a defined VM (for python function) cannot be created due to policies.\")\nfunction_instr = self.heap[{heapid!r}]\ndef defined_vm(*args):func_vm = VM();func_vm.load(function_instr);func_vm.register[\"args\"] = args;func_vm.register[\"largs\"] = len(args);func_vm.capabilities.remove(\"C_DEFINE\");return func_vm.run()\nself.register[{bindingname!r}] = defined_vm\nself.pc += 1"
                case 21:
                    r, k, v = args
                    k, v = assemble_convert(k, v)
                    return f"if not self.register.get({r!r}): self.register[{r!r}]={{}}\nself.register[{r!r}][{k}]={v}\nself.pc+=1"
                case 22:
                    r, v = args
                    v=assemble_convert(v)
                    return f'if not self.register.get({r!r}):self.register[{r!r}]=[]\nself.register[{r!r}].append({v})'
                    
                case _: raise TypeError(f"Unrecognized opcode {opc}, with args; {args}")
    def emit(self, bytecode):
        def indent(code: str,indentation: int):
            indentation = " "*indentation
            code=code.split('\n')
            for i,v in enumerate(code):
                code[i] = indentation + v
            return '\n'.join(code)
        template=f"""from mypvm.mypvm import VM\nimport sys\n\nsys.argv=["jit",__file__]+sys.argv[1:] if "__PVM_JIT__" not in globals() else sys.argv\nprint(sys.argv)\nself=VM()\nself.running = True"""
        if isinstance(bytecode[0], dict):
            template += f"; self._apply_debug_settings({bytecode[0]!r})"
            bytecode = bytecode[1:]
        template += f"\nwhile self.running:\n match self.pc:\n"
        for i,v in enumerate(bytecode):
            # Split opcode (v[0]) from args (v[1:])
            args = v[1:] if len(v) > 1 else None
            
            output = self.emit_line(v[0], v[1:] if len(v) > 1 else None)
            now=f"  case {i}:\n{indent(output,3)}\n"
            template+=now
        return template
