## Running pipelines

To run a pipeline, adapt the following snippet with the correct variables and pipeline parameters.
Please note that KFPv2 requires the use of SHA tags for pipeline templates. This snippet retrieves the SHA corresponding to the template having the *latest* tag.

```python
import google.cloud.aiplatform as aip
from kfp.registry import RegistryClient

template_artifact_registry_url = (
    f"https://{region}-kfp.pkg.dev/{project_id}/pipeline-templates"
)
client = RegistryClient(host=template_artifact_registry_url)

# Retrieve SHA tag of pipeline template
# This is required for KFPv2
pipeline_name = "your-pipeline-name"
tag = client.get_tag(package_name=pipeline_name, tag="latest")
sha_tag = tag["version"].split("/")[-1]

# Create and run Vertex AI pipeline
aip.init(
    project=project_id,
    location=region,
)

job = aip.PipelineJob(
    display_name=display_name,
    template_path=f"{template_artifact_registry_url}/{pipeline_name}/{sha_tag}",
)

# Submit job
job.submit()
```
