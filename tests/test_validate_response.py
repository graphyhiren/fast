from typing import List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

app = FastAPI()


class Item(BaseModel):
    name: str
    price: Optional[float] = None
    owner_ids: Optional[List[int]] = None


@app.get("/items/invalid", response_model=Item)
def get_invalid():
    return {"name": "invalid", "price": "foo"}


@app.get("/items/invalidnone", response_model=Item)
def get_invalid_none():
    return None


@app.get("/items/innerinvalid", response_model=Item)
def get_innerinvalid():
    return {"name": "double invalid", "price": "foo", "owner_ids": ["foo", "bar"]}


@app.get("/items/invalidlist", response_model=List[Item])
def get_invalidlist():
    return [
        {"name": "foo"},
        {"name": "bar", "price": "bar"},
        {"name": "baz", "price": "baz"},
    ]


client = TestClient(app)


def test_invalid():
    with pytest.raises(ValidationError):
        client.get("/items/invalid")


def test_invalid_none():
    with pytest.raises(ValidationError):
        client.get("/items/invalidnone")


def test_double_invalid():
    with pytest.raises(ValidationError):
        client.get("/items/innerinvalid")


def test_invalid_list():
    with pytest.raises(ValidationError):
        client.get("/items/invalidlist")
