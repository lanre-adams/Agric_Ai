from pydantic import BaseModel
from typing import List


class FarmPolygonRequest(BaseModel):
    coordinates: List[List[float]]