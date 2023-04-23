import ast

class CodebaseAnalyzerVisitor(ast.NodeVisitor):
    def __init__(self):
        self.modules = []
        self.class_context = []  # Add a stack to track the current class context

    def visit_Module(self, node):
        docstring = ast.get_docstring(node)
        module_info = {"type": "module", "docstring": docstring, "classes": [], "functions": []}
        self.modules.append(module_info)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        docstring = ast.get_docstring(node)
        class_info = {"type": "class", "name": node.name, "docstring": docstring, "functions": []}
        self.modules[-1]["classes"].append(class_info)
        self.class_context.append(class_info)  # Add the current class to the stack
        self.generic_visit(node)
        self.class_context.pop()  # Remove the current class from the stack when done

    def visit_FunctionDef(self, node):
        docstring = ast.get_docstring(node)
        function_info = {"type": "function", "name": node.name, "docstring": docstring}

        if self.class_context:  # Check if we are in a class context
            parent_class = self.class_context[-1]
            parent_class["functions"].append(function_info)
        else:
            self.modules[-1]["functions"].append(function_info)

        self.generic_visit(node)
