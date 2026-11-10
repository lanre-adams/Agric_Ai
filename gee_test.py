import os
import ee

from fastapi import APIRouter
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()


@router.get("/gee/test")
def gee_test():
    project_id = os.getenv("GEE_PROJECT_ID")

    ee.Initialize(project=project_id)

    image = ee.Image("CGIAR/SRTM90_V4")

    return {
        "status": "success",
        "project": project_id,
        "image_id": image.getInfo()["id"]
    }