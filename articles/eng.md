[Beanie](https://github.com/roman-right/beanie) - Python ODM (Object Document Mapper) for MongoDB, based on [Pydantic](https://pydantic-docs.helpmanual.io/) and [Motor](https://motor.readthedocs.io/en/stable/).

A few days ago Beanie **0.3.0** was released. The most important feature of this version is Indexes support. In this article, I would like to show in examples, what indexes are needed for and how to use them with Beanie.

For this demo I will create a geo service to search interesting places around. Next functions will be provided:
- Upload map files to create the places. Files in `.KML` format.
- Search for places by names and descriptions.
- Search for places around based on distance.

I will use FastAPI to handle the requests. It is a very popular API framework now and fits perfectly with this demonstration.

## Data Structure

To store the places I will use Beanie `Document` class. It is an abstraction over Pydantic `BaseModel` that provides methods for working with MongoDB.

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
- `geo` - geo information. As a datatype, I use `GeoObject` here. It follows the data structure `GeoJSON Point` of MongoDB. More information about this can be found [here](https://docs.mongodb.com/manual/reference/geojson/#geojson-point)

I also use the inner class `Collection`. It is optional. It helps to set up the MongoDB collection, where the documents are stored. For now, I'm just setting up the collection name there.

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

I will create an endpoint for uploading `.KML` map files to the service. To parse the file I will use the `PyKML` library.

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
        name=str(place_mark.name).strip(),
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

The endpoint receives the file in bytes format and provides it to the `PyKML` parser. It extracts all the data, and I use it to create a list of `Place` objects. Then I insert all the created objects together using the batch insert method `await Place.insert_many(places)`. It is a very efficient way for inserting data when you have many objects.

In this example, I'm using a map I found through the Google My Maps service. It is a nice map file with a collection of places in Belin. The file can be found [here](https://github.com/roman-right/beanie-index-demo/blob/main/beanie_index_demo/maps/Berlin%2C%20City%20Spy%20Map.kml), the map itself is [here](https://www.google.com/maps/d/u/0/viewer?ie=UTF8&oe=UTF8&msa=0&mid=1UjbD1lAF_fzITBuXAVQFqkgfeqs&ll=52.508127468651104%2C13.428522499999985&z=13)

## Text search

The next goal after uploading the map file is to make it able to search for places based on their names and descriptions. To do this I need to upgrade class `Place` a little:

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

This returns a list of `Place` objects, that have the string `coffee` in the name or description field. So handy.

Now I'm moving this to the endpoint and will append sorting and pagination there:

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

The endpoint returns the list according to the same search criteria, sorts it by name, and limits by `skip` and `limit` parameters.

## Geo search

Now for the tastiest part - I'm going to implement a coordinate-based search. I will create an endpoint to lookup places around by the radius. To do this, I need to add one of the geospatial indexes to the `Places`:

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

I appended the `GEOSPHERE` index to the `geo` field. Now, to find the surrounded places I will use the `aggregate` method. Suppose I am at Alexanderplatz with coordinates [13.413305998382263, 52.52203686798391] and I want to find the places in a distance of 1 kilometer:

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

Done. it returns a list of the `Place` objects within 1 kilometer of me. Also, I used `"distanceField": "distance",` parameter in the query. This means I can get the distances to each point I found. I'll update the output model a bit to achieve this:


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

I'm really impressed with the things MongoDB can do with geo indexes.

## Conclusion

I've demonstrated, what a useful and interesting thing indexes are and how comfortable it is to use them with Beanie. For sure there are many other use-cases and many other index types in MongoDB. And Beanie supports all of them and many other things. All the Beanie methods with examples can be found in the [documentation](https://roman-right.github.io/beanie/).

I've created [Beanie Discord server](https://discord.gg/ZTTnM7rMaz) where you can ask your questions, tell me about bugs, share ideas or just chat. Everyone is welcome there.

## Resources

- Demo - https://github.com/roman-right/beanie-index-demo
- Beanie project - https://github.com/roman-right/beanie
- Beanie Documentation - https://roman-right.github.io/beanie/
- Discord - https://discord.gg/ZTTnM7rMaz
