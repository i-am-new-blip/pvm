from mypvm.mypvm import VM

class Assembler:
    def __init__(self, vm=None):
        self.vm = vm or VM()

    def _split_args(self, text):
        depth = 0
        quote = None
        current = []
        args = []

        for ch in text:
            if quote:
                current.append(ch)
                if ch == quote:
                    quote = None
                continue

            if ch in "\"'":
                quote = ch
                current.append(ch)

            elif ch in "[{(":
                depth += 1
                current.append(ch)

            elif ch in "]})":
                depth -= 1
                current.append(ch)

            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []

            else:
                current.append(ch)

        if current:
            args.append("".join(current).strip())

        return args

    def _proc_args(self, args):
        return [literal_eval(i) for i in self._split_args(args)]

    def _split_instr(self, text):
        instr = text.split(" ",1)
        if len(instr)>1:
            instr, args = instr
        else: instr,args = instr[0],[]
        if "_" not in instr:
            instr = instr[0]+"_"+instr[1:]
        return [self.vm.str2i[instr.upper()],*self._proc_args(args)]
    
    def assemble(self, text: str):
        x=text.strip().split('\n')
        o=[{}]
        for i in x:
            o.append(self._split_instr(i))
        return o
    
    def _disassemble_instr(self, instr: Instruction, reassemble):
        opcode = instr[0]
        args=instr[1:]
        fn = self.vm.intructs[opcode]
        return_argument = getattr(fn,"return_argument",None)
        ignore_info = getattr(fn, "safely_ignore", [])
        register_args = getattr(fn, "register_args", [])
        name = fn.__name__
        
        if reassemble:
            crepr = lambda a:", ".join(map(repr, a))
        else:
            def handle_enum(name, key):
                match name:
                    case "MATH":
                        enum = self.vm.M_MATH_OPR
                    case "BIN":
                        enum = self.vm.M_BIN_OPR
                    case "COMP":
                        enum = self.vm.M_COMP_OPR
                    case _: print('how?')
                return list(enum.keys())[key].upper()
            def handle_ref(a):
                if isinstance(a, list) and len(a) == 1:
                    return f'r{a[0]!r}'
                if isinstance(a, list) and len(a) == 2 and type(a[0]) == str:
                    match a[0]:
                        case "raw":
                            return f'r{a[1]!r}'
                        case "ref":
                            return f'r{a[1]!r}'
                        case "list":
                            return str(list(a[1]))
                        case "tuple": 
                            return str(tuple(a[1]))
                        case "dict":
                            return str(dict(a[1]))
                return str(a)
            
            def crepr(args) -> str:
                arg = (
                    return_argument(args) 
                    if callable(return_argument) 
                    else return_argument
                )
                safe_ignore = (
                    ignore_info(args) 
                    if callable(ignore_info) 
                    else ignore_info
                )
                reg_args = (
                    register_args(args)
                    if callable(register_args)
                    else register_args
                )
                if arg is None: 
                    #print('mode 1 (no return argument)',name)
                    return ", ".join([(handle_ref(v) if i in reg_args else repr(v)) for i,v in enumerate(args) if i not in safe_ignore])
                
                elif arg == len(args)-1:
                    #print('mode 2 (ret arg is last, so ->)',name)
                    
                    items =", ".join([(handle_enum(name[2:],v) if (i==0 and name.startswith("M_") and name!="M_ADDSTRING") else handle_ref(v) if i in reg_args else repr(v)) for i,v in enumerate(args[:-1]) if i not in safe_ignore])
                    if items: items += " "
                    
                    handled = handle_ref(args[arg])
                    if not handled.startswith("r"): handled = 'r' + handled
                    
                    return f'{items}-> {handled}'
                
                else: 
                    #print('mode 3 (ret arg isnt last, starred mode)',name)
                    return ", ".join([(handle_ref(v) if i in reg_args else (f'*{v!r}' if i==arg else repr(v))) for i,v in enumerate(args) if i not in safe_ignore])

        if args:
            return f'{name} {crepr(args)}'
        return name
    
    def disassemble(self, bytecode: Program, reassemble=1):
        x=[]
        labels={}
        i=0
        for instr in bytecode:
            if isinstance(instr, dict): 
                if instr.get("line-labels"):
                    labels = {v: k for k,v in instr["line-labels"].items()}
                continue
            if labels != {} and labels.get(i) and not reassemble:
                x.append(f'{labels[i]}:')
            x.append((f'' if reassemble else f'{i:04d}: ')+self._disassemble_instr(instr,reassemble))
            i+=1 # not using enumerate cuz instr could be dict and messes up
        return '\n'.join(x)
