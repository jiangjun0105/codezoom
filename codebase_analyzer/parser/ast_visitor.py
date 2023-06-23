from __future__ import annotations

import ast


class CodeExtractor(ast.NodeVisitor):
    def __init__(self, threshold=100):
        self.code_units = {}
        self._imports = []
        self._assignments = []
        self.threshold = threshold

    def visit_FunctionDef(self, node):
        source_code = ast.unparse(node)
        self.code_units[node.name] = source_code

    def visit_ClassDef(self, node):
        source_code = ast.unparse(node)
        self.code_units[node.name] = source_code
        if len(source_code) > self.threshold:
            self.split_class_methods(node)

    def split_class_methods(self, class_node):
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef):
                method_name = f"{class_node.name}.{node.name}"
                source_code = ast.unparse(node)
                self.code_units[method_name] = source_code
                # Remove method body while keeping the method signature in the
                # class
                node.body = [ast.Pass()]
        self.code_units[class_node.name] = ast.unparse(class_node)

    def visit_Expr(self, node):
        if isinstance(
            node.value, ast.Str
        ):  # Skip string literals (e.g., module docstrings)
            return
        source_code = ast.unparse(node)
        self.code_units.append(source_code)

    def visit_Import(self, node):
        source_code = ast.unparse(node)
        self._imports.append(source_code)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        source_code = ast.unparse(node)
        self._imports.append(source_code)
        self.generic_visit(node)

    def visit_Assign(self, node):
        source_code = ast.unparse(node)
        self._assignments.append(source_code)
        self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Compare):
            left = node.test.left
            right = node.test.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == "__name__"
                and isinstance(right, ast.Constant)
                and right.value == "__main__"
            ):
                source_code = ast.unparse(node)
                # TODO: Find a better name
                self.code_units["if __name__ == __main__"] = source_code
                # for child_node in node.body:
                #     self.visit(child_node)

    @property
    def imports(self):
        return "\n".join(self._imports)

    @property
    def assignments(self):
        return "\n".join(self._assignments)
