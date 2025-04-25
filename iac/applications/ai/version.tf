terraform {
  required_version = ">= 1.3.0, < 2.0.0"
  required_providers {
    google = {
      version = "~>4.78.0"
    }
    google-beta = {
      version = "~>4.78.0"
    }
    time = {
      version = "~>0.9.1"
    }
  }
  backend "gcs" {}
}
