locals {

  cloud_run = { for k, v in var.cloud_run : k => merge(v, {
    service_account_email = var.service_accounts[v.service_account].email
    iam = merge(
      merge([for sa, roles in v.sa : { for role in roles : "${sa}/${role}" => {
        member = "serviceAccount:${var.service_accounts[sa].email}"
        role   = role
      } }]...),
      merge([for user, roles in v.users : { for role in roles : "${user}/${role}" => {
        member = "user:${user}"
        role   = role
      } }]...),
      merge([for group, roles in v.groups : { for role in roles : "${group}/${role}" => {
        member = "group:${group}"
        role   = role
      } }]...)
    ) })
  }

  updated_artifact_registry_maps = {
    for artifact_repo_name, artifact_repo_content in var.artifact_registry_repositories : artifact_repo_name => {
      location       = artifact_repo_content.location
      description    = artifact_repo_content.description
      format         = artifact_repo_content.format
      role_group_map = lookup(artifact_repo_content.role_group_map, "roles/artifactregistry.reader", null) != null ? artifact_repo_content.role_group_map : {}
    }
  }

  cloud_build = { for k, v in var.cloud_build : k => merge(v, {
    service_account = "projects/${var.project_id}/serviceAccounts/${v.service_account == "" ? var.service_accounts["cloudbuild"].email : var.service_accounts[v.service_account].email}"
    branch_regex    = coalesce(v.branch_regex, var.branch_regex)
    })
  }

  cloud_build_substitutions = merge(
    { for trigger_name, config in local.cloud_build : trigger_name => merge(config.substitutions, {
      "_REGION"                           = var.region
      "_ARTIFACT_REGISTRY_CONTAINERS_URL" = "${var.artifact_registry_repositories["pipeline-containers"].location}-docker.pkg.dev/${var.project_id}/pipeline-containers"
      "_ARTIFACT_REGISTRY_TEMPLATES_URL"  = "https://${var.artifact_registry_repositories["pipeline-templates"].location}-kfp.pkg.dev/${var.project_id}/pipeline-templates"
    }) }
  )
}
