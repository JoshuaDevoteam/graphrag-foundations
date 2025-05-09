"""Pipeline definition."""
import argparse

from kfp.registry import RegistryClient
from kfp import compiler, dsl


from components.train import train_dummy_model, retrieve_last_train_model
from components.deploy import deploy_to_cloud_run

ONLY_REDEPLOY = "only_redeploy"


parser = argparse.ArgumentParser()
parser.add_argument(
    "--project",
    help="the project ID",
    type=str,
)
parser.add_argument(
    "--region",
    help="the region where the pipeline will be stored",
    type=str,
)
parser.add_argument(
    "--pipeline-name",
    help="the name of the pipeline",
    type=str,
    default="timeseries-pipeline",
)
parser.add_argument(
    "--pipeline-file",
    help="the location to write the pipeline JSON to",
    type=str,
    default="pipeline.yaml",
)
parser.add_argument(
    "--pipeline-root",
    help="the GCS location where the pipeline export its outputs",
    type=str,
)
parser.add_argument(
    "--artifact-registry-url",
    help="the Artifact Registry URL to save the pipeline template to",
    type=str,
)
parser.add_argument(
    "--service-name",
    help="the Cloud Run service name that will serve the model",
    type=str,
)
parser.add_argument(
    "--ar-service-image",
    help="the Artifact Registry URL of the Docker image used to serve the model",
    type=str,
)

parser.add_argument(
    "--run-region",
    help="the region where Cloud Run is deployed",
    type=str,
)
parser.add_argument(
    "--run-service-account",
    help="the service account used to run the Cloud Run service",
    type=str,
)
parser.add_argument(
    "--only-redeploy",
    help="Whether only the deployment component should be executed",
    type=str,
)

parser.add_argument(
    "-t",
    "--tags",
    nargs="*",
    help="Extra tags to set on the image.",
    default=["latest"],
)
args = parser.parse_args()


@dsl.pipeline(name=args.pipeline_name, pipeline_root=f"gs://{args.pipeline_root}")
def pipeline(
    project_id: str,
    run_region: str,
    service_name: str,
    ar_service_image: str,
    service_account: str,
    pipeline_name: str,
    pipeline_root: str,
    only_redeploy: str,
):
    """Train a new model and deploy to Cloud Run."""
    with dsl.If(only_redeploy != ONLY_REDEPLOY, "train-and-deploy"):
        train_model_op = train_dummy_model()

        _ = deploy_to_cloud_run(
            project_id=project_id,
            region=run_region,
            service_name=service_name,
            trained_model=train_model_op.outputs["trained_model"],
            ar_service_image=ar_service_image,
            service_account=service_account,
        )

    with dsl.Else("only-redeploy"):

        trained_model_op = retrieve_last_train_model(
            project_id=project_id,
            pipeline_name=pipeline_name,
            bucket_name=pipeline_root,
        )

        _ = deploy_to_cloud_run(
            project_id=project_id,
            region=run_region,
            service_name=service_name,
            trained_model=trained_model_op.outputs["trained_model"],
            ar_service_image=ar_service_image,
            service_account=service_account,
        )


compiler.Compiler().compile(
    pipeline_func=pipeline,
    package_path=args.pipeline_file,
    pipeline_parameters={
        "project_id": args.project,
        "run_region": args.run_region,
        "service_name": args.service_name,
        "ar_service_image": args.ar_service_image,
        "service_account": args.run_service_account,
        "pipeline_name": args.pipeline_name,
        "pipeline_root": args.pipeline_root,
        "only_redeploy": args.only_redeploy,
    },
)

client = RegistryClient(host=args.artifact_registry_url)
templateName, versionName = client.upload_pipeline(
    file_name=args.pipeline_file,
    tags=args.tags,
    extra_headers={"description": "Sample pipeline."},
)
