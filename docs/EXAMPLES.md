# Go and Terraform demos

Complete [steps 1–3 in the README](../README.md) first: create a fresh run, put its
`greenops-exo.json` in the starter folder and open the Docker environment.
Run the following commands **inside the container**. Choose one example per run.
Both examples use the same CPU and GPU placements as the Python demo.

## Go

```sh
go run ./examples/go-static -config greenops-exo.json -action run
```

Watch your run dashboard. The example waits for both outputs and deletes its
completed VMs. Keep the terminal open while it runs.

## Terraform

```sh
terraform -chdir=examples/terraform init
terraform -chdir=examples/terraform apply -var="config_path=$PWD/greenops-exo.json"
```

Confirm the apply, then watch the two VMs in the dashboard. Terraform allocates
them; it does not wait for workload completion or delete them automatically.
After the outputs are delivered, clean up:

```sh
terraform -chdir=examples/terraform destroy -var="config_path=$PWD/greenops-exo.json"
```

Keep Terraform state and `.local/terraform-receipt.json` until cleanup succeeds.
For another run, use a fresh checkout or separate state/receipt paths.
This example uses the official Python SDK through Terraform’s built-in resource.
See [Terraform details](DEVELOPMENT.md#terraform-details) for native setup and limits.
