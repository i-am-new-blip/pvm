#!/usr/bin/env python3.14
needs = ()
import os,inspect, json, sys, builtins
from ast import literal_eval
from pprint import pprint
import traceback
MAX_READ_LIMIT = 100

type InstructionArg = (
    int
    | str
    | list["InstructionArg"]
)

type Instruction = list[InstructionArg]

type Program = list[dict | Instruction]

def arg_range(func):
    sig = inspect.signature(func)

    params = list(sig.parameters.values())

    if params and params[0].name == "self":
        params = params[1:]

    mn = 0
    mx = 0

    for p in params:
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD
        ):
            mx += 1

            if p.default is inspect.Parameter.empty:
                mn += 1

        elif p.kind == inspect.Parameter.VAR_POSITIONAL:
            mx = float("inf")

    return mn, mx
# function markers

def modifiers(**kwargs):
    def deco(fn):
        for k,v in kwargs.items():
            setattr(fn, k, v)
        return fn
    return deco

# end of function markers
class VMError(Exception):
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


    def __init__(self, message, pc=None, opcode=None, instruction=None, register=None, trace=None, tip=None, code_idx=None):
        super().__init__(message)
        self.message = message
        self.pc = pc
        self.opcode = opcode
        self.instruction = instruction
        self.register = register
        self.trace = trace
        self.tip = tip
        self.code_idx = code_idx
        
    def _fmt(self, color, text):
        return f"{color}{text}{self.RESET}"

    def __str__(self):
        out = ['']

        # header
        out.append(self._fmt(self.RED + self.BOLD, f"VMError: {self.message}"))
        
        
        if not (self.pc is None and  
                self.opcode is None and
                self.instruction is None and
                self.tip is None):
            out.append("")

        # location
        if self.pc is not None:
            text = f"  at bytecode line {self.pc}"
            if self.code_idx is not None:
                text += f" (bytecode {self.code_idx+1})"
            
            out.append(self._fmt(self.CYAN, text))
            
        if self.opcode is not None:
            out.append(self._fmt(self.GRAY, f"  opcode: {self.opcode}"))

        if self.instruction is not None:
            out.append(self._fmt(self.GRAY, f"  instruction: {self.instruction}"))

        if self.tip is not None:
            out.append(self._fmt(self.GRAY, f"  tip for fixing: {self.BOLD}{self.CYAN}{self.tip}"))

        if not (not self.trace and self.register is None):
            out.append("")

        # trace
        if self.trace:
            out.append(self._fmt(self.YELLOW, "Traceback (most recent VM call last):"))
            for i, entry in enumerate(self.trace):
                out.append(self._fmt(self.GRAY, f"  [{i}] {entry}"))

            out.append("")

        # register dump (trimmed a bit like Python would behave visually)
        if self.register is not None:
            LIM=20
            out.append(self._fmt(self.YELLOW, "Register dump:"))
            for k, v in list(self.register.items())[:LIM]:
                out.append(self._fmt(self.GRAY, f"  {k}: {v}"))

            if len(self.register) > LIM:
                out.append(self._fmt(self.GRAY, f"  ... ({len(self.register)-LIM} more)"))

        return "\n".join(out)

VMBase = type("VMBase", (type,), {})

class VM(metaclass=VMBase):
    
    #region Extras
    
    @staticmethod
    def bytecode(file):
        try:
            with open(file,'r') as f:
                new = (f.read()
                .replace('#!/usr/bin/pvm\n','')
                .replace('#!/usr/bin/env pvm\n',''))
                return json.loads(new)
        except FileNotFoundError:
            sys.exit("error: no such file")
        except OSError as e:
            sys.exit(f"error: {e.strerror} (code {e.errno})")
        except MemoryError:
            sys.exit("error: python couldn't allocate memory to read the file.")
    
    @staticmethod
    def is_deref(a, returniftrue=False):
        qualified= (isinstance(a, list) 
                and len(a) == 1
               ) or \
                (isinstance(a, list) and 
                 len(a) == 2 and 
                 type(a[0]) == str and 
                 a[0] in ["raw", "ref", "list", "tuple", "dict","refdict","reftuple","reflist"]
                )
        if qualified:
            if returniftrue:
                return returniftrue
            return True
        return None
    
    @staticmethod
    def check_deref(args, arg_idx):
        if isinstance(arg_idx, int):
            return VM.is_deref(args[arg_idx],arg_idx)
        elif isinstance(arg_idx, list):
            return [VM.check_deref(args,i) for i in arg_idx]
    def convert(self, a, b=None):
        if b is not None:
            return self.convert(a), self.convert(b)
        if not self.is_deref(a):
            return a
        if isinstance(a, list) and len(a) == 1:
            return self.register[a[0]]
        if isinstance(a, list) and len(a) == 2 and type(a[0]) == str:
            match a[0]:
                case "raw":
                    return a[1]
                case "ref":
                    return self.register[a[1]]
                case "list":
                    return list(a[1])
                case "reflist":
                    return list(map(self.convert,a[1]))
                case "tuple": 
                    return tuple(a[1])
                case "reftuple":
                    return tuple(map(self.convert,a[1]))
                case "dict":
                    return dict(a[1])
                case "refdict":
                    return dict(map(self.convert,a[1]))
    def get_tip(self, opc, chunk, this, e):
                    tip=           None
                    if opc not in self.intructs.keys():
                        tip=       "Unknown opcode. Maybe its a typo or the compiler emitted an invalid instruction?"
                    elif isinstance(e,TypeError):
                        mn, mx = self.opargs[opc]
                        if not mn <= (argc:=len(this)-1) <= mx:
                            tip=  f"Instruction expects {mn}-{mx} arguments but received {argc}."
                    elif opc in self.propsop.get("changes-pc",set()):
                        if isinstance(self.pc,str):
                            tip = f"Program counter contains unresolved label '{self.pc}'. Maybe the label does not exist?"
                        elif self.pc not in range(len(chunk)):
                            tip=  f"Jump target {self.pc} is outside the bytecode."
                    elif opc in self.propsop.get("read-register",set()):
                        if isinstance(e, IndexError):
                            tip=  f"Probrably the register you tried to get doesn't exist"
                            
                    return tip
            
    #endregion
  
    def __init__(self):
        self.register = {}
        self.callstack = []
        self.pc = 0
        self.extended_builtins = {"listed_map": lambda a,b: list(map(a,b))}
        self.stack = []
        self.running = False
        self.returns = None
        self.origin = "__init__"
        self.capabilities = {"C_DEFINE"}
        self.idx = 0
        self.code = []
        self.labels = {}
        self.heap = {}
        self.math_opr = list(self.M_MATH_OPR.keys())
        self.bin_opr = list(self.M_BIN_OPR.keys())
        self.comp_opr = list(self.M_COMP_OPR.keys())
        self.defaultsettings={
            'register-print':0,
            'printin':{
                'FCLEAR':0,
                'MMATH':0,
                'FGOTO':0,
                'FCALL':0,
                'FRET':0,
                'FIF':0
            },
            'ask-pdb':0,
            'ask-pdb-on-err':1,
            'enable-arh':1,
            'skip-arh':[],
            'line-labels':{},
            'watermark': 0,
            'heap': []
        }
        
        self.intructs={
            0:self.M_MATH,1:self.M_COMP,2:self.M_BIN,3:self.M_JOIN, 27:self.M_REP, 
            
            4:self.P_GET,5:self.P_CALL, 6:self.P_PROP,7:self.P_INDEX,
                
            8:self.C_SETR,9:self.C_HLT,10:self.C_SETLABEL,18:self.C_INITFUNC,
            19:self.C_SETH, 20: self.C_DEFINE, 21: self.C_DICTADD, 22: self.C_LISTADD,
            23: self.C_EXEC,
                
            11:self.F_GOTO,12:self.F_CALL,13:self.F_RET,14:self.F_IF,
            15:self.F_INPUT,16:self.F_PRINT,17:self.F_CLEAR,
            
            24:self.S_PUSH,25:self.S_MATH,26:self.S_CALL
        }
        
        intems= self.intructs.items()
        self.str2i   = {}
        self.opargs  = {}  # opcode's arg (min&max)
        self.opprops = {} # for seeing for a op per props
        self.propsop = {} # for getting a list of ops that have
        for opcode,f in intems:
            props={x.strip()for x in(f.__doc__ or"").split(",")}
            self.str2i[f.__name__]=opcode
            self.opprops[opcode] = props
            self.opargs[opcode] = arg_range(f)
            for i in props:
                if not self.propsop.get(i):self.propsop[i]=set()
                self.propsop[i].add(opcode)    
        
    
    # === Machine instructions ===
    # EXISTING FUNCTION DOCSTRING PROPERTIES:
    # changes-pc: doesnt do the normal (self.pc+=1)
    # sets-register: does somewhere `self.register[x]=y`
    # read-register: does somewhere `self.register[x]` (the expression)
    
    # EXISTING FUNCTION PROPERTIES:
    # return_argument  : callable | int, the argument that is the returning
    # safely_ignore    : callable | list, list of arguments to omit on `dis`
    # register_args: callable | list, marks its a rX type
    
    #region M_*
    
    #        0:self.M_MATH,
    #            1:self.M_COMP,     2:self.M_BIN,
    #        3:self.M_JOIN, 27: M_REP,
    #        28: M_MATHMULREP
    
    M_MATH_OPR = {v:i for i,v in enumerate(['+','+u','-','*','//','%','/','**','-u','|',"&","<<",">>","~","@"])}  # TODO: update on emitter
    M_BIN_OPR={v:i for i,v in enumerate(['or','not','and','xor','nand','nor'])} # TODO: update on emitter
    M_COMP_OPR={v:i for i,v in enumerate(['==','>=','<=','<','>','!=','in','is'])} # TODO: update on emitter
    
    @modifiers(return_argument = lambda a:len(a)-1)
    def M_MATH(self, opr, a, b, addr): # TODO: update on emitter
        #def topr(opri):
        #    return {v:i for i,v in self.M_MATH_OPR.items()}[opri]
        """sets-register, read-register"""
        a,b = self.convert(a,b)
        match opr:
                case 0:a=a+b
                case 1:a=+a
                case 2:a=a-b
                case 3:a=a*b
                case 4:a=a//b
                case 5:a=a%b
                case 6: a=a/b
                case 7:a=a**b
                case 8:a=-a
                case 9:a=a|b
                case 10:a=a&b
                case 11:a=a<<b
                case 12:a=a>>b
                case 13:a=~a
                case 14:a=a@b
                case _:
                    raise TypeError(f"Invalid argument {opr} must be +, -, %, / or *, unary -, unary +, **, |, &, >>, <<, unary byte inversion (~)")
        if addr is not None:
            self.register[addr] = a
            self.pc+=1
        else:
            return a 
    @modifiers(return_argument = lambda a:len(a)-1)
    def M_COMP(self, opr, a, b, addr): # TODO: update on emitter
        """sets-register, read-register"""
        a,b=self.convert(a,b)
        match opr:
            case 0:self.register[addr]=a==b
            case 1:self.register[addr]=a>=b
            case 2:self.register[addr]=a<=b
            case 3:self.register[addr]=a<b
            case 4:self.register[addr]=a>b
            case 5:self.register[addr]=a!=b
            case 6:self.register[addr]=a in b
            case 7:self.register[addr]=a is b  # TODO: update on emitter
            case _:
                raise TypeError(f"Invalid argument {opr} must be ==, >=, <=, <, >, !=, in, is")  # TODO: update on emitter
        self.pc+=1
    @modifiers(return_argument = lambda a:len(a)-1)   
    def M_BIN(self, mode, a, b, addr):
        """sets-register, read-register"""
        a,b=self.convert(a,b)
        becomes = None
        mode=self.M_BIN_OPR[mode]
        match mode:
         case 0: becomes = a or b
         case 1: becomes = not a 
         case 2: becomes = a and b  # TODO: update on emitter
         case 3: becomes = a ^ b  # TODO: update on emitter
         case 4: becomes = not (a and b) # TODO: update on emitter
         case 5: becomes = not (a or b)  # TODO: update on emitter
        self.register[addr]=becomes
        self.pc += 1
    @modifiers(return_argument = lambda a:len(a)-1)
    def M_JOIN(self, *args):
        """sets-register, read-register"""
        *args, addr = args
        if isinstance(addr,list):
            addr, sep = addr
        else:
            sep = ""
        args = sep.join(map(lambda a: str(self.convert(a)),args))
        #print(args,addr)
        if not self.register.get(addr):
            self.register[addr] = ""
        self.register[addr] += args
        #print(self.register[addr])
        self.pc += 1    
    @modifiers(return_argument = 2)
    def M_REP(self, times, what, addr, sep=""):
        """sets-register, read-register"""
        
        times, what = self.convert(times, what)
        
        args = sep.join(what for _ in range(times))
        self.register[addr] = args
        self.pc += 1

    #endregion

    #region P_*

    #            4:self.P_GET,      5:self.P_CALL, 
    #        6:self.P_PROP,
    #            7:self.P_INDEX
    @modifiers(return_argument = lambda a:len(a)-1)
    def P_GET(self, name, addr):"""sets-register""";name=self.convert(name);self.register[addr] = self.extended_builtins[name] if name in self.extended_builtins else getattr(builtins,name); self.pc += 1
    
    @modifiers(
        return_argument = lambda args: args[1]+2 if len(args[2:]) > args[1] else None,
        safely_ignore = [1],
        register_args = lambda args: [0,*VM.check_deref(args,list(range(2,2+args[1])))]
    )
    def P_CALL(self, fromAddr, argc, *rargs):
        args = [self.convert(i) for i in rargs[:argc]]
        toAddr = rargs[argc] if len(rargs) > argc else None
        
        fn = self.register.get(fromAddr)
        try:
            out = fn(*args)
            if toAddr != None: 
                self.register[toAddr] = out
        except Exception as e: raise RuntimeError(f'P_CALL failed {e}') from e
        self.pc += 1
    @modifiers(
        return_argument = lambda a:len(a)-1,
        register_args = (0,)
    )
    def P_PROP(self, startingAddr, *things):
        """sets-register, read-register"""
        addr = things[-1]
        things = things[:-1]
        obj = self.register[startingAddr]
        for v in things: obj = getattr(obj, v)
        self.register[addr] = obj
        self.pc += 1
    @modifiers(
        return_argument = lambda a: [VM.check_deref(a,1),2],
        register_args = (0,)
    )
    def P_INDEX(self, addr, index, outaddr):
        """sets-register, read-register"""
        index=self.convert(index)
        if isinstance(index,list):
            if len(index) in [2,3]:
                index=slice(*index)
        self.register[outaddr] = self.register[addr][index]
        self.pc += 1


    #endregion

    #region C_*
    #8:self.C_SETR,          9:self.C_HLT,
    #10:self.C_SETLABEL,     18: self.C_INITFUNC,
    #19:self.C_SETH,         20: self.C_DEFINE,
    #21:self.C_DICTADD,        22: self.C_LISTADD,
    #23:self.C_EXEC
    @modifiers(return_argument = lambda a:len(a)-1)
    def C_SETR(self, v, addr):"""sets-register"""; self.register[addr] = v; self.pc += 1
    @modifiers(return_argument = lambda a:len(a)-1)
    def C_SETH(self, v, addr):"""sets-register"""; self.register[addr] = self.heap[v]; self.pc += 1
    
    @modifiers(return_argument = lambda a:None if len(a) == 0 else 0)
    def C_HLT(self, arg=None):
        self.running = False
        self.returns = self.convert(arg)
        if self.debugsettings['register-print']:pprint(self.register)
    
    def C_SETLABEL(self, label,goto=None):
        """changes-pc"""
        self.labels[label] = self.pc+1;self.pc = goto if goto else self.pc+1 # put
        # if self.code[self.idx][self.pc+1][0] != 18: raise RuntimeError("Every function must start with C_INITFUNC (opc number 18)")
    
    def C_INITFUNC(self, *args):
        """sets-register, read-register"""
        hasargs = self.callstack[-1][1]
        if not args: 
            self.pc+=1
            return
        for i,v in zip(map(self.convert,hasargs), args):
            self.register[v] = i
        self.callstack[-1][3] = args
        self.pc+=1
    
    @modifiers(return_argument = 0, register_args = lambda a: VM.check_deref(a,[1,2]))
    def C_DICTADD(self, r, k, v):
        """sets-register, read-register"""
        k, v = self.convert(k,v)
        if not self.register.get(r): self.register[r]={}
        self.register[r][k]=v
        self.pc+=1
    
    @modifiers(return_argument = 0, register_args = lambda a: VM.check_deref(a,1))
    def C_LISTADD(self, r, v, extend=False):
        """sets-register, read-register"""
        v = self.convert(v)
        if not self.register.get(r): self.register[r]=[]
        if not extend:
            self.register[r].append(v)
        else:
            self.register[r].extend(v)
        self.pc+=1
    
    @modifiers(return_argument = 0)
    def C_DEFINE(self, bindingname: str | int, heapid: int):
        """sets-register"""
        if 'C_DEFINE' not in self.capabilities : raise PermissionError("a defined VM (for python function) cannot be created due to policies.")
        function_instr = self.heap[heapid]
        def defined_vm(*args):
            #print("RAW PY ARGS:", args)
            #print("FUNC:", defined_vm)
            #print("QUALNAME:", defined_vm.__qualname__)
            func_vm = VM()
            func_vm.load(function_instr)
            func_vm.register["args"] = args
            func_vm.register["largs"] = len(args)
            func_vm.capabilities.remove("C_DEFINE")
            y=func_vm.run()
            #print(func_vm, func_vm.register)
            return y
        self.register[bindingname] = defined_vm
        self.pc += 1
        
    def C_EXEC(self, instr): # instr number 23
        """read-register"""
        instr = self.convert(instr)
        self.code= self.code[:self.idx+1]+[instr]+self.code[self.idx+1:]
        self.C_HLT()
        # its that simple??
        
    #endregion

    #region F_*

    # 11:self.F_GOTO, 12:self.F_CALL,
    #    13:self.F_RET,     14:self.F_IF,
    # 15:self.F_INPUT,
    #    16:self.F_PRINT,   17:self.F_CLEAR

    
    def F_GOTO(self, addr): 
        """changes-pc"""
        addrn = addr if isinstance(addr,int) else self.labels[addr]
        if self.debugsettings['printin']['FGOTO']: print(f'jumping (f_goto) from {self.pc} to {addr} ({addrn})')
        self.pc=addrn # put
    
    def F_CALL(self, addr, args=None, returnvaladdr=None): 
        """changes-pc, read-register"""
        self.callstack.append([self.pc + 1,map(self.convert,args),returnvaladdr, None]); 
        newaddr = addr if isinstance(addr,int)else self.labels[addr]
        if self.code[self.idx][newaddr][0] != 18: raise RuntimeError("Every function must start with C_INITFUNC (opc number 18)")
        if self.debugsettings['printin']['FCALL']: print(f'jumping (f_call) from {self.pc} to {addr} ({newaddr})')
        self.pc=newaddr # put    
    
    def F_RET(self, returns=None):
        """changes-pc, sets-register, read-register"""
        if not self.callstack: raise RuntimeError("callstack empty")
        pc,_,returning,delete  = self.callstack.pop()
        if returning and returns:
            self.register[returning] = self.register[returns]
            self.register.pop(returns)
        elif not(returning == None and returns == None):
            raise TypeError("Mismatch in function requests.")
        if delete: self.register.pop(delete)
        if self.debugsettings['printin']['FRET']: print(f'jumping (f_ret) from {self.pc} to {pc}')
        self.pc = pc # put
    
    @modifiers(register_args=(0,))
    def F_IF(self, binOpAddr, addr):
        """changes-pc, read-register"""
        if self.register[binOpAddr]:
            pc = self.labels.get(addr,addr)
            if self.debugsettings['printin']['FIF']: print(f'jumping (f_if) from {self.pc} to {pc}')
            self.pc=pc
        else: self.pc+=1
       
    @modifiers(return_argument = lambda a:len(a)-1) 
    def F_INPUT(self, text, addr):
        """sets-register"""
        self.register[addr] = input(text)
        self.pc +=1
    
    def F_PRINT(self, addr):"""read-register"""; print(self.convert(addr)); self.pc +=1
    
    def F_CLEAR(self, sr: list | int | str, er: int=None):
        """sets-register"""
        print = print if self.debugsettings['printin']['FCLEAR'] else lambda *a:0
        if type(sr)==list:
            for i in sr:
                print(f'deleting addr {i!r}, from pc {self.pc}')
                self.register.pop(i)
        elif type(sr) == int:
            if er!=None:
                for i in range(sr,er+1):
                    print(f'deleting addr {i!r}, from pc {self.pc}')
                    self.register.pop(i)
            else:
                print(f'deleting addr {sr!r}, from pc {self.pc}')
                self.register.pop(sr)
        else:print(f'deleting addr {sr!r}, from pc {self.pc}'); self.register.pop(sr)
        self.pc +=1
    
    #endregion
    
    #region S_*
    
    # 24: S_PUSH, 25: S_MATH, 26: S_CALL
    
    def S_PUSH(self, *a):
        if isinstance(a, list):
            if len(a)!=1:
                return [self.S_PUSH(i) for i in a] # S_PUSH(a,b,c,d)
            elif isinstance(a[0],list):
                return [self.S_PUSH(i) for i in a] # S_PUSH([a,b,c,d])
        self.stack.append(a[0])
        self.pc += 1

    @modifiers(return_argument = lambda a: None if len(a) == 1 else 1)
    def S_MATH(self, opr, dst = None):
        """sets-register, read-register"""
        a,b = self.stack.pop(),self.stack.pop()
        print(a,b)
        
        res = self.M_MATH(opr, a,b,None)
        if dst is None:
            self.stack.append(res)
        else:
            self.register[dst] = res
        self.pc += 1
    
    @modifiers(return_argument = lambda a: None if len(a) == 0 else 0)
    def S_CALL(self, dst = None):
        """sets-register """
        fn = self.stack.pop()
        fn = self.convert(fn)
        try:
            out = fn()
            if dst is None:
                self.stack.append(out)
            else:
                self.register[dst] = out
        except Exception as e: raise RuntimeError(f'S_CALL failed {e}')
        self.pc+=1
    
    # === Load & run ===
    def load(self, bytecode: list):
        self.code.append(bytecode)
        return self # as i am a cool guy
    def _apply_debug_settings(self, debugsettings: dict):
        
            def deep_merge(a, b):
                out = dict(a)
                for k, v in b.items():
                    if isinstance(v, dict) and isinstance(out.get(k), dict):
                        out[k] = deep_merge(out[k], v)
                    else:
                        out[k] = v
                return out
            if isinstance(debugsettings,dict):
                debugsettings = deep_merge(self.defaultsettings, debugsettings)
                x=True
            else:
                debugsettings=self.defaultsettings
                x=False
            self.debugsettings=debugsettings
            if debugsettings['line-labels']:self.labels = debugsettings['line-labels']
            if debugsettings['heap']:self.heap=debugsettings['heap']
            return x
    def _run_instr(self, instr, ran, arp = False):
        opc, args = instr[0], instr[1:]
        ran.append({"lineno": self.pc,
            "opcode": opc,
            "name": self.intructs[opc].__name__,
            "instruction": instr,
            "arguments": args
        })
        if arp: raise RecursionError(f"Reached max limit of repeating the running of line {arp}.")
                    
        func = self.intructs[opc]
        try:
            func(*args)
            return opc
        except Exception as e: 
            return [opc, e]
    def run(self):
        if self.defaultsettings['watermark']: print(f'PVM v1.5.4')
        retlist = []
        while self.idx < len(self.code):
            chunk = self.code[self.idx]
            
            # DEBUGSETTINGS
            if self._apply_debug_settings(chunk[0]):
                chunk = chunk[1:]
            
            debugsettings = self.debugsettings
            ran,lines,arp,ignored = [],{},False,debugsettings['skip-arh']
            self.pc = 0
            self.returns = None
            self.running = True
            while self.running:
                try:
                    opc = self._run_instr(chunk[self.pc], ran, arp)
                    if isinstance(opc,list):
                        opc,err = opc
                        raise err from err
                except Exception as e:
                    if isinstance(e, VMError): raise
                
                    # decide behavior HERE, not outside chaos
                    self.running = False
                    self.last_error = VMError(
                        message=f"{type(e).__name__}: {e}",
                        pc=self.pc,
                        opcode=opc,
                        instruction=chunk[self.pc],
                        register=self.register.copy(),
                        trace=ran,
                        tip=self.get_tip(opc, chunk, chunk[self.pc], e),
                        code_idx=self.idx
                    )
                    raise self.last_error from e
                
                else:
                    if debugsettings['enable-arh'] and self.pc not in ignored:
                        if self.pc in lines: 
                            lines[self.pc]+=1
                            if lines[self.pc] > MAX_READ_LIMIT:
                                q=input(f"Anti-repeat handler: the line {self.pc} has been read for the {lines[self.pc]}th time, continue Running, Crash or Skip line forever (s)? [r/c/s] ")
                                if q == 'c':arp = self.pc
                                elif q == 's':ignored.append(self.pc)
                                elif q.startswith('s'):
                                    q=int(q[1:])
                                    ignored.extend(range(self.pc,self.pc+q+1))
                        else: 
                            lines[self.pc] = 0
            if debugsettings['ask-pdb']:
                w=input('Would you like to run PDB? [y/n] ')
                if w=='y':breakpoint()
            self.idx += 1
            retlist.append(self.returns)
        return retlist
