from enum import Enum
from typing import Tuple, Optional

from pydantic.main import BaseModel

from models.data_models import Place


class ResponseStatuses(str, Enum):
    OK = "OK"


class StatusResponse(BaseModel):
    status: ResponseStatuses


class PlacesByWordInput(BaseModel):
    search_words: str
    skip: Optional[int] = None
    limit: Optional[int] = None


class PlacesAroundInput(BaseModel):
    coordinates: Tuple[float, float]
    radius: float = 1000


class PlaceWithDistance(Place):
    distance: float
