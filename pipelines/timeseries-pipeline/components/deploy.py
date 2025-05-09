"""Deploy a model to Cloud Run in a new revision of the service."""
from kfp.dsl import component, Input, Model


@component(
    base_image="python:3.10-slim",
    packages_to_install=[
        "google-cloud-run==0.10.1",
    ],
)
def deploy_to_cloud_run(
    project_id: str,
    region: str,
    service_name: str,
    trained_model: Input[Model],
    ar_service_image: str,
    service_account: str,
):
    """From a service name, deployed the new trained model to Cloud Run."""
    from google.cloud import run_v2

    run_client = run_v2.ServicesClient()

    run_env_vars = [
        run_v2.EnvVar(
            name="_MODEL_PATH",
            value=trained_model.path,
        )
    ]
    run_container = [
        run_v2.Container(
            image=ar_service_image,
            env=run_env_vars,
        )
    ]
    revision_template = run_v2.RevisionTemplate(
        service_account=service_account,
        containers=run_container,
    )

    run_service = run_v2.Service(
        name=f"projects/{project_id}/locations/{region}/services/{service_name}",
        template=revision_template,
    )

    # Initialize request argument(s)
    request = run_v2.UpdateServiceRequest(
        service=run_service,
        allow_missing=True,
    )

    # Make the request
    operation = run_client.update_service(request=request)

    print("Waiting for operation to complete...")

    response = operation.result()

    # Handle the response
    print(response)
