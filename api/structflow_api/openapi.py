"""OpenAPI 3.1 document assembled from the pydantic schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from structflow_api import schemas

REF = "#/components/schemas/{model}"


def _ref(model: type[BaseModel]) -> dict[str, str]:
    return {"$ref": REF.format(model=model.__name__)}


def _json(model: type[BaseModel], description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": _ref(model)}}}


def _errors(*codes: int) -> dict[str, Any]:
    text = {
        400: "Malformed request (body is not JSON)",
        404: "Pool not found",
        409: "Conflict (duplicate pool name)",
        422: "Validation error",
    }
    return {str(c): _json(schemas.ErrorResponse, text[c]) for c in codes}


POOL_ID = {"name": "pool_id", "in": "path", "required": True, "schema": {"type": "integer"}}


def build_spec() -> dict[str, Any]:
    components: dict[str, Any] = {}
    for model in (
        schemas.PoolCreate,
        schemas.PoolOut,
        schemas.PoolList,
        schemas.Scenario,
        schemas.CashFlowResponse,
        schemas.PriceRequest,
        schemas.PriceResponse,
        schemas.ScenarioResponse,
        schemas.ErrorResponse,
    ):
        mode: Literal["validation", "serialization"] = (
            "validation" if model in (schemas.PoolCreate, schemas.PriceRequest) else "serialization"
        )
        schema = model.model_json_schema(ref_template=REF, by_alias=True, mode=mode)
        components.update(schema.pop("$defs", {}))
        components[model.__name__] = schema

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "StructFlow API",
            "version": "0.1.0",
            "description": (
                "Agency MBS pass-through cash flow projection and pricing. Rates are "
                "annual decimals; yields compound monthly; prices are per 100 face."
            ),
        },
        "paths": {
            "/pools": {
                "get": {
                    "summary": "List pools",
                    "responses": {"200": _json(schemas.PoolList, "Pools")},
                },
                "post": {
                    "summary": "Create a pool from loan-level data",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _ref(schemas.PoolCreate)}},
                    },
                    "responses": {
                        "201": _json(schemas.PoolOut, "Pool created"),
                        **_errors(400, 409, 422),
                    },
                },
            },
            "/pools/{pool_id}": {
                "get": {
                    "summary": "Get a pool",
                    "parameters": [POOL_ID],
                    "responses": {"200": _json(schemas.PoolOut, "Pool"), **_errors(404)},
                }
            },
            "/pools/{pool_id}/cashflows": {
                "post": {
                    "summary": "Project monthly cash flows under a prepayment scenario",
                    "parameters": [POOL_ID],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _ref(schemas.Scenario)}},
                    },
                    "responses": {
                        "200": _json(schemas.CashFlowResponse, "Cash flows"),
                        **_errors(400, 404, 422),
                    },
                }
            },
            "/pools/{pool_id}/price": {
                "post": {
                    "summary": "Price from yield, or yield from price, with WAL and risk",
                    "parameters": [POOL_ID],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _ref(schemas.PriceRequest)}},
                    },
                    "responses": {
                        "200": _json(schemas.PriceResponse, "Analytics (recorded as a run)"),
                        **_errors(400, 404, 422),
                    },
                }
            },
            "/pools/{pool_id}/scenarios": {
                "get": {
                    "summary": "Analytics across the standard PSA scenario grid",
                    "parameters": [
                        POOL_ID,
                        {
                            "name": "yield",
                            "in": "query",
                            "schema": {"type": "number"},
                            "description": "Price every scenario at this yield "
                            "(default: the pool's pass-through rate)",
                        },
                        {
                            "name": "price",
                            "in": "query",
                            "schema": {"type": "number"},
                            "description": "Solve each scenario's yield at this price",
                        },
                    ],
                    "responses": {
                        "200": _json(schemas.ScenarioResponse, "Scenario grid"),
                        **_errors(404, 422),
                    },
                }
            },
        },
        "components": {"schemas": components},
    }


SWAGGER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>StructFlow API docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({url: "openapi.json", dom_id: "#swagger-ui"});</script>
</body>
</html>
"""
