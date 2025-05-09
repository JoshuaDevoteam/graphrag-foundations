"""Serving app."""
import logging
import os
from functools import lru_cache

from flask import Flask

MODEL_PATH = os.environ.get("_MODEL_PATH")

app = Flask(__name__)
# creating the logger object
logger = logging.getLogger()


@lru_cache(1)
def get_model():
    """Retrieve the ML model."""
    # TODO retrieve model
    print("Retrieving model")


if __name__ == "__main__":
    app.run(
        debug=False,
        host="0.0.0.0",  # nosec - Listen to all interfaces
        port=int(os.environ.get("PORT", 8080)),
    )
