from typing import List

from fastapi import File, APIRouter
from pykml import parser

from models.data_models import Place, GeoObject
from models.interface_models import (
    PlaceWithDistance,
    StatusResponse,
    PlacesAroundInput,
    PlacesByWordInput,
    ResponseStatuses,
)

place_router = APIRouter()


@place_router.post("/upload/", response_model=StatusResponse)
async def places_from_file(file: bytes = File(...)):
    root = parser.fromstring(file)
    places = []
    for folder in root.Document.Folder:
        for place_mark in folder.Placemark:
            try:
                description = str(place_mark.description).strip()
            except AttributeError:
                description = ""
            place = Place(
                name=str(place_mark.name).strip(),
                description=description,
                geo=GeoObject(
                    coordinates=str(place_mark.Point.coordinates).strip().split(",")[:2]
                ),
            )
            places.append(place)
    await Place.insert_many(places)
    return StatusResponse(status=ResponseStatuses.OK)


@place_router.post("/search/", response_model=List[Place])
async def places_by_word(input_data: PlacesByWordInput):
    return await Place.find_many(
        {"$text": {"$search": input_data.search_words}},
        skip=input_data.skip,
        limit=input_data.limit,
        sort="name",
    ).to_list()


@place_router.post("/around/", response_model=List[PlaceWithDistance])
async def places_by_radius(input_data: PlacesAroundInput):
    point = GeoObject(coordinates=input_data.coordinates)

    return await Place.aggregate(
        [
            {
                "$geoNear": {
                    "near": point.dict(),
                    "distanceField": "distance",
                    "maxDistance": input_data.radius,
                }
            }
        ],
        item_model=PlaceWithDistance,
    ).to_list()
