"""Pydantic request/response models for the sampling API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ChildPolicy = Literal["none", "all"]


class TableSpec(BaseModel):
    name: str = Field(..., min_length=1)
    primary_key: list[str] = Field(..., min_length=1)


class ForeignKeySpec(BaseModel):
    name: Optional[str] = None
    table: str
    columns: list[str] = Field(..., min_length=1)
    ref_table: str
    ref_columns: list[str] = Field(..., min_length=1)


class RegistryRequest(BaseModel):
    tables: list[TableSpec]
    foreign_keys: list[ForeignKeySpec] = []


class ChildTablePolicy(BaseModel):
    table: str
    policy: ChildPolicy = "none"


class SampleRequest(BaseModel):
    start_table: str
    total: int = Field(..., ge=1)
    seed: int = 0
    group_field: Optional[str] = None
    quotas: dict[str, int] = {}
    child_policies: list[ChildTablePolicy] = []


class Violation(BaseModel):
    foreign_key: str
    source_table: str
    source_columns: list[str]
    ref_table: str
    ref_columns: list[str]
    missing_keys: list[dict[str, Any]]
    count: int
    note: Optional[str] = None


class ColumnInfo(BaseModel):
    name: str
    type: str


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]
    row_count: int
    primary_key: Optional[list[str]] = None


class CatalogResponse(BaseModel):
    tables: list[TableInfo]
    foreign_keys: list[ForeignKeySpec]
    registered: bool
