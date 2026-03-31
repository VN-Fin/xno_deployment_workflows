import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/hello-api")
def hello():
    env_name = os.getenv("RUN_ENV", "unknown")
    return {"message": f"hello {env_name}"}
