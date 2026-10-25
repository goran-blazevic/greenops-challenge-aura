terraform {
  required_version = "= 1.13.4"
}

# The built-in provider invokes the official Python binding. This is intentionally
# not an assertion of compatibility with the Exoscale Terraform provider.
variable "config_path" {
  type        = string
  description = "Path to the run's downloaded greenops-exo.json (not its contents)."
}
variable "python" {
  type    = string
  default = "python3"
}
variable "receipt_path" {
  type    = string
  default = "../../.local/terraform-receipt.json"
}

resource "terraform_data" "static_baseline" {
  input = {
    config  = abspath(var.config_path)
    plan    = abspath("${path.module}/../static-plan.json")
    receipt = abspath(var.receipt_path)
    driver  = abspath("${path.module}/../python/terraform_driver.py")
    python  = var.python
  }
  triggers_replace = [filesha256("${path.module}/../static-plan.json"), abspath(var.config_path)]

  provisioner "local-exec" {
    interpreter = [self.input.python, self.input.driver]
    command     = "deploy"
    environment = {
      GREENOPS_CONFIG  = self.input.config
      GREENOPS_PLAN    = self.input.plan
      GREENOPS_RECEIPT = self.input.receipt
    }
  }
  provisioner "local-exec" {
    when        = destroy
    interpreter = [self.input.python, self.input.driver]
    command     = "destroy"
    environment = {
      GREENOPS_CONFIG  = self.input.config
      GREENOPS_RECEIPT = self.input.receipt
    }
  }
}
output "receipt_path" {
  value = terraform_data.static_baseline.output.receipt
}
