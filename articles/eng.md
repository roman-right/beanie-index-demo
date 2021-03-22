[Beanie](https://github.com/roman-right/beanie) - Python micro ODM (Object Document Mapper) for MongoDB, based on [Pydantic](https://pydantic-docs.helpmanual.io/) and [Motor](https://motor.readthedocs.io/en/stable/).

A few days ago Beanie **0.3.0** was released. The most important feature of this release is Indexes support. In this article, I would like to show in examples, what indexes are needed for and how to use them with Beanie.

As an example, I will create a geo service to search interesting places around. Next functions will be provided:
- Map files uploading to create the places. Files in `.KML` format.
- Search places by names and descriptions.
- Search places around by radius.

I will use FastAPI to handle the requests. It is very popular now and perfectly fits this demonstration.

## Data Structure

To store the places I will use Beanie `Document` class. It is an abstraction over Pydantic `BaseModel` which provides methods to work with MongoDB.

```python
from enum import Enum
from typing import Tuple

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
```

`Place` data model contains fields:

- `name` - the name of the place
- `description` - a short description of the place
- `geo` - geo information. As a datatype, I use `GeoObject` here. It follows the data structure `GeoJSON Point` of MongoDB. You can find more information about this [here](https://docs.mongodb.com/manual/reference/geojson/#geojson-point)

Also, I use inner class `Collection`. It is optional. It helps to set up MongoDB collection, where documents will be stored. For now, I set up only the name of the collection there.

## Initialisation

I'm creating the FastAPI app and init Beanie with the `Place` document structure. No surprises here.

```python
# ... some code skipped

@app.on_event("startup")
async def app_init():
    client = motor.motor_asyncio.AsyncIOMotorClient(Settings().mongo_dsn)
    await init_beanie(client.beanie_db, document_models=[Place])
    app.include_router(place_router, prefix="/v1", tags=["places"])
```

## Upload the map file

I will create an endpoint to upload `.KML` map files to the service. To parse the file I'll use the `PyKML` library.

```python
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
        name=str(place_mark.search_words).strip(),
        description=description,
        geo=GeoObject(coordinates=str(place_mark.Point.coordinates).strip().split(",")[:2])  # long-lat
      )
      places.append(place)
  await Place.insert_many(places)
  return StatusResponse(status=ResponseStatuses.OK)
```

{% details Click to see request details %}

POST `localhost:10001/v1/upload` with file

Output:

```json
{
    "status": "OK"
}
```

{% enddetails %}

The endpoint receives the file in bytes format and provides it to the `PyKML` parser. It is extracting all the data, and I use it to create a list of `Place` objects. Then I insert all the created objects together using batch insert method `await Place.insert_many(places)`. It is a very efficient way to insert data when you have many objects.

In this example, I'm using a map, which I found on the Google My Maps service. It is a nice map file with a collection of places in Belin.

## Text search

The next goal after the map file uploading is to make it able to search places by the names and descriptions. For this I have to upgrade class `Place` a little:

```python
class Place(Document):
    name: str
    description: str
    geo: GeoObject

    class Collection:
        name = "places"
        indexes = [
            [("name", pymongo.TEXT), ("description", pymongo.TEXT)],
        ]
```

I added `TEXT` index for the `name` and `description` fields. Now I can use MongoDB text search to find places:

```python
await Place.find_many({"$text": {"$search": "coffee"}}).to_list()
```

This will return a list of `Place` objects, which have `coffee` string in the name or description field. So handy.
Now I'll move this to the endpoint and will append sorting and pagination there:

```python
class PlacesByPhraseInput(BaseModel):
    search_phrase: str
    skip: Optional[int] = None
    limit: Optional[int] = None


@place_router.post("/search/", response_model=List[Place])
async def places_by_name(input_data: PlacesByPhraseInput):
    return await Place.find_many(
        {"$text": {"$search": input_data.search_phrase}},
        skip=input_data.skip,
        limit=input_data.limit,
        sort="name"
    ).to_list()
```

{% details Click to see request details %}

POST `localhost:10001/v1/search`

Input:

```json
{
    "search_phrase": "coffee",
    "limit": 2
}
```

Output:

```json
[
    {
        "_id": "605861b0a7bad9ea7250d130",
        "name": "19grams",
        "description": "Tiny hole in the wall serving Tres Cabezas locally roasted coffee & homemade cakes. Small space that fills up in winter then opens up onto the street in the summer. Perfect spot for a coffee refresh on the way to visit the Eastside gallery & Oberbaumbrucke.                                                                           Mon- Fri 08.oo- 18.oo Sat- Sun 10.oo- 18.oo",
        "geo": {
            "type": "Point",
            "coordinates": [
                13.4447623999999,
                52.4999605
            ]
        }
    },
    {
        "_id": "605861b0a7bad9ea7250d131",
        "name": "19grams",
        "description": "After 15 years of serving house roasted coffee paired with exceptional homemade cakes. Loads of seating, in'n'out & a perfect pitstop from the weekend fleamarkets at Boxhagener Platz & RAW.                                                         Mon- 08.oo- 20.oo Sat- Sun 09.oo- 20.oo",
        "geo": {
            "type": "Point",
            "coordinates": [
                13.4687180999999,
                52.507127
            ]
        }
    }
]
```

{% enddetails %}

The endpoint will return the list by the same search criteria, will sort it by name, and limit by `skip` and `limit` parameters.

## Geo search

And the tastiest thing now - I'll implement a coordinates-based search. I will create an endpoint to lookup places around by the radius. To do this I have to add one of the geo indexes to the `Places`:

```python
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
```

I appended the `GEOSPHERE` index to the `geo` field. Now, to find the surrounded places I will use the `aggregate` method. Let's assume I'm staying on the Alexanderplatz with coordinates [13.413305998382263, 52.52203686798391] and I want to find the places in a distance of 1 kilometer:

```python
point = GeoObject(coordinates=[13.413305998382263, 52.52203686798391])
radius = 1000  # 1km

places = await Place.aggregate(
    [
        {
            "$geoNear": {
                "near": point.dict(),
                "distanceField": "distance",
                "maxDistance": radius,
            }
        }
    ],
    item_model=Place
).to_list()
```

Done. it will return a list of the `Place` objects within 1 kilometer of me. Also, I used `"distanceField": "distance",` parameter in the query. It means I can receive the distances to each point I found. I'll update the output model a little to reach this:


```python
class PlaceWithDistance(Place):
    distance: float


places = await Place.aggregate(
    [
        {
            "$geoNear": {
                "near": point.dict(),
                "distanceField": "distance",
                "maxDistance": radius,
            }
        }
    ],
    item_model=PlaceWithDistance  # Here I use new output model
).to_list()
```

Now it also provides a distance together with other places information. I will wrap it to the endpoint:

```python
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
        item_model=PlaceWithDistance
    ).to_list()
```

{% details Click to see request details %}

POST `localhost:10001/v1/around`

Input:

```json
{
    "coordinates": [13.413305998382263, 52.52203686798391],
    "radius": 2000
}
```

Output:

```json
[
    {
        "_id": "605861b0a7bad9ea7250d0ea",
        "name": "Serious Communist buildings",
        "description": "",
        "geo": {
            "type": "Point",
            "coordinates": [
                13.418898,
                52.52335
            ]
        },
        "distance": 405.9842140775255
    },
    {
        "_id": "605861b0a7bad9ea7250d0f1",
        "name": "1.Berliner DDR Motorrad Museum",
        "description": "",
        "geo": {
            "type": "Point",
            "coordinates": [
                13.4080193,
                52.5238593
            ]
        },
        "distance": 411.55085454343913
    },
    ...
]
```

{% enddetails %}

Done!

## Conclusion

I showed, what a useful and interesting thing indexes are and how comfortable it is to use them with Beanie. For sure there are many other use-cases and many other index types in MongoDB. Beanie supports all of them. I hope, it will help you to build applications, experiments, and proofs of concepts.

I've created [Beanie Discord server](https://discord.gg/ZTTnM7rMaz) where you can ask your questions, tell me about bugs, share ideas or just chat. Everyone is welcome there.

## Resources

- Project from the article - https://github.com/roman-right/beanie
- Beanie project - https://github.com/roman-right/beanie
- Beanie Documentation - https://roman-right.github.io/beanie/
- Discord - https://discord.gg/ZTTnM7rMaz





