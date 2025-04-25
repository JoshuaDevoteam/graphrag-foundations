artifact_registry_repositories = {
  pipeline-containers = {
    description    = "Repository containing pipeline Docker containers."
    format         = "DOCKER"
    location       = "europe-west1"
    role_group_map = {}
  }
  pipeline-packages = {
    description    = "Repository containing pipeline Python packages."
    format         = "PYTHON"
    location       = "europe-west1"
    role_group_map = {}
  }
  pipeline-templates = {
    description    = "Repository containing Kubeflow Pipelines templates."
    format         = "KFP"
    location       = "europe-west1"
    role_group_map = {}
  }
}
branch_regex = ".*"
buckets = {
  datasets = {
    name   = "pj-joshua-foundations-test-datasets"
    region = "europe-west1"
  }
  models = {
    name   = "pj-joshua-foundations-test-models"
    region = "europe-west1"
  }
}
environment = ""
project_id  = "pj-joshua-foundations-test"
repo_name   = "joshua-foundations"
repo_owner  = "devoteamgcloud"
region      = "europe-west1"
service_accounts = {
  terraform = {
    create = false
    email  = "sa-terraform@pj-joshua-foundations-test.iam.gserviceaccount.com"
  }
  cloudbuild = {
    create = false
    email  = "sa-cloudbuild@pj-joshua-foundations-test.iam.gserviceaccount.com"
  }
}
