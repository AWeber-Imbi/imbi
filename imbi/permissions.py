import ast
import inspect
import typing

from tornado.routing import _RuleList


def find_permissions(routes: _RuleList) -> typing.Set[str]:
    """Return a set of distinct permissions for all of the endpoints that
     are registered in the system.

     :param routes: Routes that will be passed in to app creation

     """
    permissions, processed = set({}), set({})

    def find_decorators(node):
        """Find the decorators on a node and if the decorator name matches
        the expected value (require_permission), add it to the permission set.

        :param ast.Node node: The node to check

        """
        for n in node.decorator_list:
            if isinstance(n, ast.Call):
                name = n.func.attr if isinstance(n.func, ast.Attribute) \
                    else n.func.id
            else:
                name = n.attr if isinstance(n, ast.Attribute) else n.id
            if name == 'require_permission':
                [permissions.add(a.s) for a in n.args]

    # Iterate across all endpoints
    for endpoint in routes:
        for cls in inspect.getmro(endpoint.target):
            if cls in processed:
                continue
            processed.add(cls)
            node_iter = ast.NodeVisitor()
            node_iter.visit_FunctionDef = find_decorators
            node_iter.visit_AsyncFunctionDef = find_decorators
            try:
                node_iter.visit(ast.parse(inspect.getsource(cls)))
            except TypeError:
                pass
    return permissions
