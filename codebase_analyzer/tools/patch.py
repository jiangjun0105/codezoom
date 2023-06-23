"""Utilities for patching functions before deinfining tools"""

import functools
import inspect


def patch_tool(func, **fixed_args):
    """Patch a function with fixed arguments to create a new function with the
    fixed arguments excluded in the new signature. This is necessary to hide the
    fixed argumetns from the LLM."""

    original_signature = inspect.signature(func)
    new_params = [
        param
        for name, param in original_signature.parameters.items()
        if name not in fixed_args
    ]
    new_signature = original_signature.replace(parameters=new_params)

    @functools.wraps(func)
    def new_function(*args, **kwargs):
        kwargs.update(fixed_args)
        return func(*args, **kwargs)

    new_function.__signature__ = new_signature
    return new_function
