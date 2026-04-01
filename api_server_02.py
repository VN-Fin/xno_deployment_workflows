import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/hello-api-02")
def hello():
    env_name = os.getenv("RUN_ENV", "unknown")
    arg_01 = os.getenv("EXAMPLE_ARG_01", "not set")
    arg_02 = os.getenv("EXAMPLE_ARG_02", "not set")
    return {
        "service": "api-02",
        "message": f"hello {env_name}",
        "build_args": {
            "EXAMPLE_ARG_01": arg_01,
            "EXAMPLE_ARG_02": arg_02,
        },
    }
