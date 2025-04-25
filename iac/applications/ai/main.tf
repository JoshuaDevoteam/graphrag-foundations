provider "google" {
  project                     = var.project_id
  region                      = var.region
  impersonate_service_account = var.service_accounts["terraform"].email
}

provider "google-beta" {
  project                     = var.project_id
  region                      = var.region
  impersonate_service_account = var.service_accounts["terraform"].email
}

module "buckets" {
  for_each = var.buckets

  source = "/Users/joshuavink/Devoteam/foundations/cloud-foundations/cloud_foundations/modules/cloud-storage"

  project_id                  = var.project_id
  name                        = each.value.name
  bucket_location             = each.value.region
  bucket_storage_class        = "STANDARD"
  bucket_force_destroy        = false
  bucket_uniform_level_access = true
}

module "cloud_build" {
  for_each = local.cloud_build
  # tflint-ignore: terraform_module_pinned_source
  source = "/Users/joshuavink/Devoteam/foundations/cloud-foundations/cloud_foundations/modules/cloud-build"

  project         = var.project_id
  trigger_name    = each.key
  config_path     = each.value.path
  included_files  = each.value.included
  ignored_files   = each.value.ignored
  regex           = each.value.branch_regex
  on              = each.value.on
  repo_owner      = var.repo_owner
  repo_name       = var.repo_name
  substitutions   = local.cloud_build_substitutions[each.key]
  service_account = each.value.service_account
}

module "run" {
  for_each = local.cloud_run

  source = "/Users/joshuavink/Devoteam/foundations/cloud-foundations/cloud_foundations/modules/cloud-run"

  project                 = var.project_id
  name                    = each.key
  location                = each.value.location
  service_account_email   = each.value.service_account_email
  cpu                     = each.value.cpu
  memory                  = each.value.memory
  max_instance_count      = each.value.max_instance_count
  min_instance_count      = each.value.min_instance_count
  startup_cpu_boost       = each.value.startup_cpu_boost
  timeout                 = each.value.timeout
  environment_variables   = each.value.environment_variables
  port                    = each.value.port
  iam                     = each.value.iam
  secrets                 = each.value.secrets
  traffic                 = each.value.traffic
  vpc_access_connector_id = each.value.vpc_access_connector_id
}

module "artifact_repository" {
  for_each = local.updated_artifact_registry_maps

  source = "/Users/joshuavink/Devoteam/foundations/cloud-foundations/cloud_foundations/modules/artifact-registry"

  project_id = var.project_id

  artifact_registry_repository_id  = each.key
  artifact_registry_format         = each.value.format
  artifact_registry_location       = each.value.location
  artifact_registry_description    = each.value.description
  artifact_registry_role_group_map = each.value.role_group_map
}
