"""JSON Schema 부분집합 검증기 (표준 라이브러리만).

지원 키워드: type, enum, const, required, properties, additionalProperties(bool),
items, minItems, maxItems, minimum, maximum, minLength, pattern, oneOf, $ref
(같은 파일 `#/...` 또는 schemas 폴더의 다른 파일 `x.schema.json#/...`).
그 밖의 키워드는 무시한다. 이 검증기는 이 저장소의 스키마 파일 전용이며 전체 draft 2020-12를 구현하지 않는다.
"""
import json
import os
import re

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")
_cache = {}


def load_schema(name):
    if name not in _cache:
        with open(os.path.join(SCHEMA_DIR, name), "r", encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


def _type_ok(value, t):
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "null":
        return value is None
    return False


def _resolve(ref, root_name, root):
    file_part, _, frag = ref.partition("#")
    if file_part:
        name = file_part
        doc = load_schema(name)
    else:
        name, doc = root_name, root
    node = doc
    for part in [p for p in frag.split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return name, doc, node


def _validate(value, schema, name, root, path, errors):
    if "$ref" in schema:
        n2, d2, node = _resolve(schema["$ref"], name, root)
        _validate(value, node, n2, d2, path, errors)
        return
    if "oneOf" in schema:
        matches = 0
        for sub in schema["oneOf"]:
            sub_err = []
            _validate(value, sub, name, root, path, sub_err)
            if not sub_err:
                matches += 1
        if matches != 1:
            errors.append(f"{path or '$'}: oneOf에 {matches}개가 맞음")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '$'}: {schema['const']!r}이어야 함 (값 {value!r})")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path or '$'}: enum {schema['enum']} 중 하나여야 함 (값 {value!r})")
        return
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, x) for x in types):
            errors.append(f"{path or '$'}: 형식 {types} 아님 (값 {type(value).__name__})")
            return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path or '$'}: {schema['minimum']} 이상이어야 함 (값 {value})")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path or '$'}: {schema['maximum']} 이하여야 함 (값 {value})")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path or '$'}: 길이 {schema['minLength']} 이상이어야 함")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path or '$'}: 패턴 {schema['pattern']} 불일치 (값 {value!r})")
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path or '$'}: 항목 {schema['minItems']}개 이상이어야 함")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path or '$'}: 항목 {schema['maxItems']}개 이하여야 함")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], name, root, f"{path}[{i}]", errors)
    elif isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path or '$'}: 필수 키 {key!r} 없음")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                _validate(value[key], sub, name, root, f"{path}.{key}" if path else key, errors)
        addl = schema.get("additionalProperties", True)
        if isinstance(addl, dict):
            for key, v in value.items():
                if key not in props:
                    _validate(v, addl, name, root, f"{path}.{key}" if path else key, errors)
        elif addl is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path or '$'}: 허용되지 않는 키 {key!r}")


def validate(value, schema_name, max_errors=20):
    """schemas/<schema_name> 기준으로 검증하고 오류 문자열 목록을 돌려준다(빈 목록이면 통과)."""
    root = load_schema(schema_name)
    errors = []
    _validate(value, root, schema_name, root, "", errors)
    return errors[:max_errors]
