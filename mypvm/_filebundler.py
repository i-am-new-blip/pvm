#!/usr/bin/env python3.14
import ast, copy, sys, os,importlib
from ast import *
from pathlib import Path
from itertools import chain
from glob import glob

TBCOPIED = ast.parse("@f(1)\ndef _(m,e,r):pass")
TBCOPIED2= ast.parse("""decohack=type('',(),{'__init__':lambda s:(setattr(s,'require',None),setattr(s,'r',{}),setattr(s,'c',{}),None)[-1],'__call__':lambda s,i:(lambda f:(s.r.__setitem__(i,f),f)[-1]),'__enter__':lambda s:s,'__exit__':lambda s,_,z,x:(r:=lambda n:(s.c[n]['e']if n in s.c else(s.c.__setitem__(n,(m:={'e':{}})),s.r[n](m,m["e"],r),m['e'])[-1]),setattr(s,'require',r),None)[-1]})\nwith decohack() as f:pass""")
class BundlerError(Warning): pass
class MiniBundler(ast.NodeTransformer):
    def __init__(self, bundlermap,exportname='e', requirename='r'):
        self.exports = set()
        self.imports = set()
        self.external_imports = []
        self.ename = exportname
        self.rname = requirename
        self.bmap = bundlermap

    # transform: export(x) -> x
    def visit_Assign(self, node):
        self.generic_visit(node)
        if not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "export"
        ):
            return node
        if node.value.args:
            export_value = node.value.args[0]
            export_name = node.targets[0].id
            node.value = export_value
            node.targets = [ast.Subscript(ast.Name(self.ename),ast.Constant(export_name))]
            return node
        else:
            raise SyntaxError("an export NEEDS an value to be exported...")
    # transform: import x -> x = require("x")
    def visit_Import(self, node):
        new_nodes = []

        for alias in node.names:
            name = alias.name
            external = name not in self.bmap
            if not external:
                self.imports.add(name)
            else:
                return node
            call = ast.Call(
                        ast.Name(self.rname),
                        [ast.Constant(self.bmap.get(name,name))],
             )
            new_nodes.append(
                ast.Assign(
                    [ast.Name(alias.asname or name)], #
                    call
                    # expects r(modulename)
                ) # 
            )

        return new_nodes

    # transform: from x import y
    def visit_ImportFrom(self, node):
        new_nodes = []

        module = node.module

        for alias in node.names:
            name = alias.name
            external = module not in self.bmap
            if not external:
                self.imports.add(name)
            else:
                #self.external_imports.append((module,name))
                return node
            value = ast.Subscript(
                        value=ast.Call(
                            ast.Name(self.rname),[ast.Constant(self.bmap.get(module,module))],
                        ), # r(module)[name]
                        slice=ast.Constant(name) 
                    )
            new_nodes.append(
                ast.Assign([ast.Name(alias.asname or name)],value)
                #          name = value
            )

        return new_nodes
def bundlecode(code, transformer,dependency_graph,idno):
    tree = ast.parse(code)
    new_tree = transformer.visit(tree)
    dependency_graph[idno] = {*map(lambda a:(transformer.bmap[a]),transformer.imports)}
    ast.fix_missing_locations(new_tree)
    wrapper = copy.deepcopy(TBCOPIED)
    wrapper.body[0].body = new_tree.body
    wrapper.body[0].decorator_list[0].args[0]=ast.Constant(idno)
    return wrapper

def bundlefiles(bundler_map,contents):
    visited = set()
    order = []
    def define_external_import(imports):
        copied = copy.deepcopy(TBCOPIED).body[0]
        copied.decorator_list[0].args=[Constant(imports)]
        copied.body=[Assign([Subscript(Name('m'),Constant(imports))],[Call(Name('__import__'),[Constant(imports)])])]
        return copied
    def walk(mod,graph):
        if mod in visited:
            return

        visited.add(mod)

        for dep in graph[mod]:
            walk(dep,graph)

        order.append(mod)
    dependency_graph = {}
    transformer = MiniBundler(bundler_map)
    bundled=[]
    #externals = []
    for (i,v) in zip(bundler_map.values(),contents):
        copiedtransformer = copy.deepcopy(transformer)
        bundled.append(bundlecode(v,copiedtransformer,dependency_graph,i))
        #externals.append(copiedtransformer.external_imports)
    #externals = list(chain.from_iterable(externals))
    #imports = map(define_external_import,externals)
    wrapper = copy.deepcopy(TBCOPIED2)
    wrapper.body[1].body = [*map(lambda a:a.body[0],bundled)] #,*imports]
    main_file_id = bundler_map.get('main')
    if not main_file_id:
        raise BundlerError("The main.py file, said in the bundler's code, was not provided.")
    else:
        wrapper.body.append(ast.Module([ast.Expr(ast.Call(ast.Attribute(ast.Name('f'),'require'),[ast.Constant(main_file_id)]))]))
        walk(main_file_id,dependency_graph)
    ast.fix_missing_locations(wrapper)
    return wrapper, dependency_graph, order 

def bundlepaths(files):
    arg1 = {i:v for v,i in enumerate([Path(p).stem for p in files])}
    arg3 = [Path(a).resolve().read_text() for a in files]
    return bundlefiles(arg1,arg3)