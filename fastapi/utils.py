import re
import warnings
from dataclasses import is_dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, Type, Union, cast

import fastapi
from dirty_equals import IsStr
from fastapi._compat import (
    PYDANTIC_V2,
    BaseConfig,
    ModelField,
    PydanticSchemaGenerationError,
    Undefined,
    UndefinedType,
    Validator,
    lenient_issubclass,
)
from fastapi.datastructures import DefaultPlaceholder, DefaultType
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

if TYPE_CHECKING:  # pragma: nocover
    from .routing import APIRoute


def is_body_allowed_for_status_code(status_code: Union[int, str, None]) -> bool:
    if status_code is None:
        return True
    # Ref: https://github.com/OAI/OpenAPI-Specification/blob/main/versions/3.1.0.md#patterned-fields-1
    if status_code in {
        "default",
        "1XX",
        "2XX",
        "3XX",
        "4XX",
        "5XX",
    }:
        return True
    current_status_code = int(status_code)
    return not (current_status_code < 200 or current_status_code in {204, 304})


def get_path_param_names(path: str) -> Set[str]:
    return set(re.findall("{(.*?)}", path))


def create_response_field(
    name: str,
    type_: Type[Any],
    class_validators: Optional[Dict[str, Validator]] = None,
    default: Optional[Any] = Undefined,
    required: Union[bool, UndefinedType] = Undefined,
    model_config: Type[BaseConfig] = BaseConfig,
    field_info: Optional[FieldInfo] = None,
    alias: Optional[str] = None,
) -> ModelField:
    """
    Create a new response field. Raises if type_ is invalid.
    """
    class_validators = class_validators or {}
    if PYDANTIC_V2:
        field_info = field_info or FieldInfo(
            annotation=type_, default=default, alias=alias
        )
    else:
        field_info = field_info or FieldInfo()
    kwargs = {"name": name, "field_info": field_info}
    if not PYDANTIC_V2:
        kwargs.update(
            {
                "type_": type_,
                "class_validators": class_validators,
                "default": default,
                "required": required,
                "model_config": model_config,
                "alias": alias,
            }
        )
    try:
        return ModelField(**kwargs)
    except (RuntimeError, PydanticSchemaGenerationError):
        raise fastapi.exceptions.FastAPIError(
            "Invalid args for response field! Hint: "
            f"check that {type_} is a valid Pydantic field type. "
            "If you are using a return type annotation that is not a valid Pydantic "
            "field (e.g. Union[Response, dict, None]) you can disable generating the "
            "response model from the type annotation with the path operation decorator "
            "parameter response_model=None. Read more: "
            "https://fastapi.tiangolo.com/tutorial/response-model/"
        ) from None


def create_cloned_field(
    field: ModelField,
    *,
    cloned_types: Optional[Dict[Type[BaseModel], Type[BaseModel]]] = None,
) -> ModelField:
    if PYDANTIC_V2:
        return field
    # _cloned_types has already cloned types, to support recursive models
    if cloned_types is None:
        cloned_types = {}
    original_type = field.type_
    if is_dataclass(original_type) and hasattr(original_type, "__pydantic_model__"):
        original_type = original_type.__pydantic_model__
    use_type = original_type
    if lenient_issubclass(original_type, BaseModel):
        original_type = cast(Type[BaseModel], original_type)
        use_type = cloned_types.get(original_type)
        if use_type is None:
            use_type = create_model(original_type.__name__, __base__=original_type)
            cloned_types[original_type] = use_type
            for f in original_type.__fields__.values():
                use_type.__fields__[f.name] = create_cloned_field(
                    f, cloned_types=cloned_types
                )
    new_field = create_response_field(name=field.name, type_=use_type)
    new_field.has_alias = field.has_alias
    new_field.alias = field.alias
    new_field.class_validators = field.class_validators
    new_field.default = field.default
    new_field.required = field.required
    new_field.model_config = field.model_config
    new_field.field_info = field.field_info
    new_field.allow_none = field.allow_none
    new_field.validate_always = field.validate_always
    if field.sub_fields:
        new_field.sub_fields = [
            create_cloned_field(sub_field, cloned_types=cloned_types)
            for sub_field in field.sub_fields
        ]
    if field.key_field:
        new_field.key_field = create_cloned_field(
            field.key_field, cloned_types=cloned_types
        )
    new_field.validators = field.validators
    new_field.pre_validators = field.pre_validators
    new_field.post_validators = field.post_validators
    new_field.parse_json = field.parse_json
    new_field.shape = field.shape
    new_field.populate_validators()
    return new_field


def generate_operation_id_for_path(
    *, name: str, path: str, method: str
) -> str:  # pragma: nocover
    warnings.warn(
        "fastapi.utils.generate_operation_id_for_path() was deprecated, "
        "it is not used internally, and will be removed soon",
        DeprecationWarning,
        stacklevel=2,
    )
    operation_id = name + path
    operation_id = re.sub(r"\W", "_", operation_id)
    operation_id = operation_id + "_" + method.lower()
    return operation_id


def generate_unique_id(route: "APIRoute") -> str:
    operation_id = route.name + route.path_format
    operation_id = re.sub(r"\W", "_", operation_id)
    assert route.methods
    operation_id = operation_id + "_" + list(route.methods)[0].lower()
    return operation_id


def deep_dict_update(main_dict: Dict[Any, Any], update_dict: Dict[Any, Any]) -> None:
    for key, value in update_dict.items():
        if (
            key in main_dict
            and isinstance(main_dict[key], dict)
            and isinstance(value, dict)
        ):
            deep_dict_update(main_dict[key], value)
        elif (
            key in main_dict
            and isinstance(main_dict[key], list)
            and isinstance(update_dict[key], list)
        ):
            main_dict[key] = main_dict[key] + update_dict[key]
        else:
            main_dict[key] = value


def get_value_or_default(
    first_item: Union[DefaultPlaceholder, DefaultType],
    *extra_items: Union[DefaultPlaceholder, DefaultType],
) -> Union[DefaultPlaceholder, DefaultType]:
    """
    Pass items or `DefaultPlaceholder`s by descending priority.

    The first one to _not_ be a `DefaultPlaceholder` will be returned.

    Otherwise, the first item (a `DefaultPlaceholder`) will be returned.
    """
    items = (first_item,) + extra_items
    for item in items:
        if not isinstance(item, DefaultPlaceholder):
            return item
    return first_item


def match_pydantic_error_url(error_type: str) -> IsStr:
    return IsStr(regex=rf"^https://errors\.pydantic\.dev/.*/v/{error_type}")
