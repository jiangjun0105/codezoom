import os
import ast

from .ast_visitor import CodebaseAnalyzerVisitor

def traverse_directory(directory_path):
    python_files = []
    
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    
    return python_files

def parse_codebase(python_files):
    ast_trees = []
    codebase_info = []
    
    for file in python_files:
        try:
            with open(file, "r", encoding="utf-8") as source_file:
                source_code = source_file.read()
            
            tree = ast.parse(source_code)
            ast_trees.append((file, tree))

            visitor = CodebaseAnalyzerVisitor()
            visitor.visit(tree)
            codebase_info.append({"file": file, "modules": visitor.modules})
        except Exception as e:
            print(f"Error parsing {file}: {e}")
    
    return codebase_info
