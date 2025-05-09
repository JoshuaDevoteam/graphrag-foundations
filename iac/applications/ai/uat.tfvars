artifact_registry_repositories = {
  pipeline-containers = {
    description = "Repository containing pipeline Docker containers."
    format = "DOCKER"
    location = "europe-west1"
    role_group_map = {}
  }
  pipeline-packages = {
    description = "Repository containing pipeline Python packages."
    format = "PYTHON"
    location = "europe-west1"
    role_group_map = {}
  }
  pipeline-templates = {
    description = "Repository containing Kubeflow Pipelines templates."
    format = "KFP"
    location = "europe-west1"
    role_group_map = {}
  }
}
branch_regex = "release.*"
buckets = {
  datasets = {
    name = "pj-joshua-foundations-mid-datasets"
    region = "europe-west1"
  }
  models = {
    name = "pj-joshua-foundations-mid-models"
    region = "europe-west1"
  }
  timeseries-pipeline = {
    name = "pj-joshua-foundations-mid-pipelines-timeseries-pipeline"
    region = "europe-west1"
  }
  graphrag = {
    name = "pj-joshua-foundations-mid-genai-graphrag"
    region = "europe-west1"
  }
}
environment = ""
project_id = "pj-joshua-foundations-mid"
repo_name = "joshua-foundations"
repo_owner = "devoteamgcloud"
region = "europe-west1"
service_accounts = {
  terraform = {
    create = false
    email = "sa-terraform@pj-joshua-foundations-mid.iam.gserviceaccount.com"
  }
  cloudbuild = {
    create = false
    email = "sa-cloudbuild@pj-joshua-foundations-mid.iam.gserviceaccount.com"
  }
  sa-vertex-timeseries-pipeline-uat = {
    create = false
    email = "sa-vertex-timeseries-pipeline-uat@pj-joshua-foundations-mid.iam.gserviceaccount.com"
  }
  sa-run-timeseries-pipeline-uat = {
    create = false
    email = "sa-run-timeseries-pipeline-uat@pj-joshua-foundations-mid.iam.gserviceaccount.com"
  }
  sa-graphrag-uat = {
    create = false
    email = "sa-graphrag-uat@pj-joshua-foundations-mid.iam.gserviceaccount.com"
  }
}
cloud_build = {
  timeseries-pipeline = {
    included = [
      "pipelines/timeseries-pipeline/**"
    ]
    path = "pipelines/timeseries-pipeline/cloudbuild.yaml"
    substitutions = {
      _PIPELINE_NAME = "timeseries-pipeline"
    }
  }
  graphrag = {
    included = [
      "services/graphrag/**"
    ]
    path = "services/graphrag/cloudbuild.yaml"
    substitutions = {
      _SERVICE_NAME = "graphrag"
    }
  }
}
cloud_run = {
  timeseries-pipeline = {
    location = "europe-west1"
    service_account = "sa-run-timeseries-pipeline-uat"
    cpu = "1"
    memory = "4Gi"
    sa = {
      sa-run-timeseries-pipeline-uat = [
        "roles/run.invoker"
      ]
    }
  }
  graphrag = {
    location = "europe-west1"
    service_account = "sa-graphrag-uat"
    cpu = "1"
    memory = "4Gi"
    sa = {
      sa-graphrag-uat = [
        "roles/run.invoker"
      ]
    }
  }
}
