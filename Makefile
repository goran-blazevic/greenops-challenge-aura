.PHONY: test image

test:
	go test ./...
	python3 -m unittest discover -s tests -v

image:
	docker build --build-arg TARGETARCH=$$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/;s/x86_64/amd64/') -t greenops-toolchain:local .

.PHONY: archive
archive:
	mkdir -p .local
	git archive --format=zip --prefix=participant-starter/ HEAD -o .local/participant-starter.zip

# ---------------------------------------------------------------- live runs
# Credentials come from this run's env file, which the orchestrator finds itself
# (nearest greenops.env / greenops-*.env / .env from here upwards), so nothing
# needs exporting by hand. Override any variable on the command line.
PYTHON    ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
DOCKER    ?= sudo docker
IMAGE     ?= greenops-orchestrator:local
ENV_FILE  ?= $(shell $(PYTHON) -m orchestrator.run env --path)
STATE_DIR ?= $(CURDIR)/.local/state
ARGS      ?=

.PHONY: env
env:
	$(PYTHON) -m orchestrator.run env

.PHONY: run
run:
	$(PYTHON) -m orchestrator.run run $(ARGS)

.PHONY: cleanup
cleanup:
	$(PYTHON) -m orchestrator.run cleanup $(ARGS)

.PHONY: docker-build
docker-build:
	$(DOCKER) build -f Dockerfile.orchestrator -t $(IMAGE) .

# The submission image, handed the same env file as a read-only mount.
.PHONY: docker-run
docker-run: _creds
	mkdir -p $(STATE_DIR)
	$(DOCKER) run --rm -it \
	  -v "$(ENV_FILE):/opt/greenops-starter/greenops.env:ro" \
	  -v "$(STATE_DIR):/state" -e GREENOPS_STATE=/state/orch.json \
	  $(IMAGE) $(ARGS)

.PHONY: docker-cleanup
docker-cleanup: _creds
	mkdir -p $(STATE_DIR)
	$(DOCKER) run --rm -it \
	  -v "$(ENV_FILE):/opt/greenops-starter/greenops.env:ro" \
	  -v "$(STATE_DIR):/state" -e GREENOPS_STATE=/state/orch.json \
	  --entrypoint python $(IMAGE) -m orchestrator.run cleanup

# This checkout mounted into the toolchain image: no rebuild between edits.
.PHONY: docker-dev
docker-dev: _creds
	mkdir -p $(STATE_DIR)
	$(DOCKER) run --rm -it \
	  -v "$(CURDIR):/workspace" -w /workspace \
	  -v "$(ENV_FILE):/workspace/.local/greenops.env:ro" \
	  -e GREENOPS_ENV_FILE=/workspace/.local/greenops.env \
	  -e GREENOPS_STATE=/workspace/.local/state/orch.json \
	  --entrypoint python ghcr.io/exogmi/greenops-challenge-starter-kit:latest \
	  -m orchestrator.run run $(ARGS)

.PHONY: _creds
_creds:
	@test -n "$(ENV_FILE)" || { \
	  echo "no credentials file found. Put this run's download (greenops-*.env) in"; \
	  echo "$(CURDIR) or any parent directory, then retry; 'make env' shows the search."; \
	  exit 1; }
