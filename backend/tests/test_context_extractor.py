from __future__ import annotations

import pytest

from app.pipeline.context_extractor import SpecError, extract_context, sanitize_text
from tests.conftest import FIXTURES


@pytest.fixture(scope="module")
def ctx():
    return extract_context((FIXTURES / "openapi_search.yaml").read_text(encoding="utf-8"))


def test_only_safe_operations(ctx):
    assert [(op.method.value, op.path) for op in ctx.operations] == [
        ("GET", "/search"),
        ("GET", "/items/{id}"),
        ("HEAD", "/tags"),
    ]
    assert ctx.skipped_operations == 2  # POST /search, DELETE /items/{id}


def test_metadata(ctx):
    assert ctx.title == "Catalog Search API"  # control char removed
    assert ctx.version == "1.2.0"
    assert ctx.spec_version == "3.0.3"
    assert ctx.servers == ["http://sut-demo:8001"]


def test_parameters(ctx):
    op = ctx.find_operation("get", "/search")
    assert op is not None and op.operation_id == "searchItems"
    q, limit, page, sort, category = (op.param(n) for n in ("q", "limit", "page", "sort", "category"))
    assert q.required and q.type == "string" and q.example == "jazz"
    assert (limit.type, limit.minimum, limit.maximum, limit.default) == ("integer", 1, 100, 10)
    assert limit.description == "Max results per page"  # whitespace normalized
    assert page.required is False and page.default == 1
    assert sort.enum == ["id_asc", "price_asc", "price_desc"]
    assert category.enum == ["vinyl", "cd", "cassette"]  # resolved through $ref
    assert op.param("X-Trace") is None
    assert op.unsupported_params == ["header:X-Trace"]


def test_path_level_parameters_are_inherited(ctx):
    op = ctx.find_operation("GET", "/items/{id}")
    p = op.param("id", "path")
    assert p.required and p.type == "integer"


def test_response_fields_with_refs_allof_and_int_status_code(ctx):
    fields = ctx.find_operation("GET", "/search").response_fields
    assert fields["$.total"] == "integer"
    assert fields["$.results"] == "array<object>"
    assert fields["$.results[*].id"] == "integer"  # from allOf Base
    assert fields["$.results[*].price"] == "number"
    assert fields["$.results[*].category"] == "string"
    assert fields["$.results[*].tags"] == "array<string>"


def test_recursive_schema_does_not_loop(ctx):
    shape = ctx.find_operation("GET", "/items/{id}").response_shape
    assert shape["related"] == ["any"]


def test_operation_without_json_response(ctx):
    op = ctx.find_operation("HEAD", "/tags")
    assert op.response_shape is None and op.response_fields == {}


def test_prompt_text(ctx):
    text = ctx.to_prompt_text()
    assert "## GET /search  [searchItems]" in text
    assert "- param limit (query, integer, min=1, max=100, default=10) — Max results per page" in text
    assert '- param sort (query, string, enum=["id_asc", "price_asc", "price_desc"])' in text
    assert "response fields: $.total: integer" in text
    assert "POST" not in text


def test_swagger2():
    doc = {
        "swagger": "2.0",
        "info": {"title": "Pets", "version": "1"},
        "host": "petstore.example.com",
        "basePath": "/v2",
        "schemes": ["https"],
        "paths": {
            "/pet/findByStatus": {
                "get": {
                    "parameters": [
                        {
                            "name": "status",
                            "in": "query",
                            "type": "array",
                            "items": {"type": "string", "enum": ["available", "sold"]},
                        },
                        {"name": "body", "in": "body", "required": True, "schema": {}},
                    ],
                    "responses": {
                        "200": {"schema": {"type": "array", "items": {"$ref": "#/definitions/Pet"}}},
                    },
                }
            }
        },
        "definitions": {"Pet": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    }
    ctx = extract_context(doc)
    assert ctx.servers == ["https://petstore.example.com/v2"]
    op = ctx.operations[0]
    status = op.param("status")
    assert (status.type, status.items_type) == ("array", "string")
    assert op.unsupported_params == ["body:body"]
    assert op.response_fields == {"$": "array<object>", "$[*]": "object", "$[*].id": "integer"}


def test_openapi31_nullable_types_and_undeclared_placeholder():
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/users/{userId}/posts": {
                "get": {
                    "parameters": [{"name": "limit", "in": "query", "schema": {"type": ["integer", "null"]}}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": {"n": {"type": ["null", "number"]}}}
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    op = extract_context(doc).operations[0]
    assert op.param("limit").type == "integer"
    assert op.param("userId", "path").required
    assert op.response_fields == {"$.n": "number"}


@pytest.mark.parametrize(
    "raw",
    [
        "not: [valid",
        "just a string",
        '{"openapi": "3.0.0"}',
        '{"openapi": "1.0", "paths": {}}',
        '{"paths": {}}',
    ],
)
def test_invalid_specs(raw):
    with pytest.raises(SpecError):
        extract_context(raw)


def test_sanitize_text():
    assert sanitize_text("a\x00b\n\n c") == "a b c"
    assert sanitize_text("x" * 300, 10) == "x" * 9 + "…"
    assert sanitize_text("   ") is None
    assert sanitize_text(42) is None
