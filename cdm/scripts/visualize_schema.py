import inspect
import os
import typing
from typing import List
from pydantic import BaseModel
from definitions import cdm_schema

def get_inner_type(type_hint):
    """Recursively unwraps List, Optional, Union to find the underlying Pydantic model."""
    origin = typing.get_origin(type_hint)
    args = typing.get_args(type_hint)
    
    if origin is None:
        return type_hint if inspect.isclass(type_hint) and issubclass(type_hint, BaseModel) else None
    
    if origin is list or origin is List:
        return get_inner_type(args[0])
    
    if origin is typing.Union:
        # Check all args, return the first one that is a Model (simplification)
        for arg in args:
            inner = get_inner_type(arg)
            if inner:
                return inner
        return None
    
    return None

def get_type_str(type_hint):
    """Returns a clean string representation of the type hint."""
    origin = typing.get_origin(type_hint)
    args = typing.get_args(type_hint)
    
    if origin is None:
        if hasattr(type_hint, "__name__"):
            return type_hint.__name__
        return str(type_hint)
    
    if origin is typing.Union:
        # Filter out NoneType for Optional
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return f"{get_type_str(non_none_args[0])}?"
        return " | ".join(get_type_str(arg) for arg in non_none_args)
    
    if origin is list or origin is List:
        return f"List[{get_type_str(args[0])}]"
    
    if hasattr(origin, "__name__"):
        return f"{origin.__name__}[{', '.join(get_type_str(arg) for arg in args)}]"
    
    return str(type_hint)

def generate_mermaid():
    models = []
    for name, obj in inspect.getmembers(cdm_schema):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == cdm_schema.__name__:
            models.append(obj)

    mermaid_code = "classDiagram\n"
    
    # Define classes with properties
    for model in models:
        mermaid_code += f"    class {model.__name__} {{\n"
        for field_name, field_info in model.model_fields.items():
            type_hint = field_info.annotation
            type_str = get_type_str(type_hint)
            mermaid_code += f"        +{type_str} {field_name}\n"
        mermaid_code += "    }\n"

    # Define relationships
    for model in models:
        for field_name, field_info in model.model_fields.items():
            type_hint = field_info.annotation
            target_model = get_inner_type(type_hint)
            
            if target_model and target_model in models:
                # Determine relationship type (list vs single)
                origin = typing.get_origin(type_hint)
                is_list = origin is list or origin is List
                
                arrow = "<--" if not is_list else "*--"
                
                mermaid_code += f"    {model.__name__} {arrow} {target_model.__name__} : {field_name}\n"
    
    # Output to file
    with open("cdm.mermaid", "w") as f:
        f.write(mermaid_code)
    print(f"Mermaid file saved to: {os.path.abspath('cdm.mermaid')}")

    # Generate Link
    import base64
    import json
    
    state = {
      "code": mermaid_code,
      "mermaid": {"theme": "default"}
    }
    json_str = json.dumps(state)
    base64_str = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8')
    print(f"\nVisualize online:\nhttps://mermaid.live/edit#pjson_{base64_str}")

if __name__ == "__main__":
    generate_mermaid()
