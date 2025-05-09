"""Create a dummy model to be deployed later."""
from kfp.dsl import component, Model, Output


@component(
    base_image="python:3.10-slim",
    packages_to_install=[
        "scikit-learn==1.3.2",
        "numpy==1.26.2",
        "hickle==5.0.2",
    ],
)
def train_dummy_model(trained_model: Output[Model]):
    """Train a ML model."""
    import hickle as hkl
    import numpy as np
    from sklearn.linear_model import LinearRegression

    X = np.array([[1, 1], [1, 2], [2, 2], [2, 3]])
    y = np.dot(X, np.array([1, 2])) + 3
    reg = LinearRegression().fit(X, y)

    # Dump data to file
    hkl.dump(reg, trained_model.path)
    print(trained_model.path)


@component(
    base_image="python:3.10-slim",
    packages_to_install=[
        "scikit-learn==1.3.2",
        "numpy==1.26.2",
        "hickle==5.0.2",
        "google-cloud-storage==2.10.0",
    ],
)
def retrieve_last_train_model(
    project_id: str, pipeline_name: str, bucket_name: str, trained_model: Output[Model]
):
    """Retrieve the last model that was successfully generated."""
    import hickle as hkl

    # import numpy as np
    # from sklearn.linear_model import LinearRegression

    from google.cloud import storage

    sc = storage.Client(project=project_id)
    bucket = sc.bucket(bucket_name)

    blobs = bucket.list_blobs(match_glob=f"**/{pipeline_name}**/*trained_model")
    most_recent_blob = None

    for blob in blobs:
        if most_recent_blob is None:
            most_recent_blob = blob
        else:
            if most_recent_blob.updated < blob.updated:
                most_recent_blob = blob
    if most_recent_blob is not None:
        gcs_location = f"/gcs/{bucket_name}/{most_recent_blob.name}"
        print("Found our most recent blob: ", most_recent_blob.name)
        model = hkl.load(gcs_location)
        hkl.dump(model, trained_model.path)
    else:
        print("Did not find any blob")
