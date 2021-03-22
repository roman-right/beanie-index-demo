from enum import Enum
from typing import Tuple

import pymongo
from beanie import Document
from pydantic import BaseModel


class GeoType(str, Enum):
    point = "Point"


class GeoObject(BaseModel):
    type: GeoType = GeoType.point
    coordinates: Tuple[float, float]


class Place(Document):
    name: str
    description: str
    geo: GeoObject

    class Collection:
        name = "places"
        indexes = [
            [("name", pymongo.TEXT), ("description", pymongo.TEXT)],  # TEXT indexes
            [("geo", pymongo.GEOSPHERE)],  # GEO index
        ]
