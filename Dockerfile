# syntax=docker/dockerfile:1
FROM golang:1.25-bookworm@sha256:3b4a11519ad929d1e1d261a12cff056f0c85b735253d7d861346b9c6f8b36437 AS go-toolchain
FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
ARG TARGETARCH
LABEL org.opencontainers.image.source="https://github.com/exogmi/greenops-challenge-starter-kit"
LABEL org.opencontainers.image.title="Energy Bridge GreenOps participant toolchain"
LABEL org.opencontainers.image.description="Exoscale CLI, Terraform, Go and Python with static orchestration examples"
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl git jq make unzip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/opt/venv/bin:/usr/local/go/bin:/usr/local/bin:${PATH}" \
    GOTOOLCHAIN=local \
    TF_IN_AUTOMATION=1 \
    TF_CHECKPOINT_DISABLE=1
COPY scripts/install-tools.sh /tmp/install-tools.sh
RUN sh /tmp/install-tools.sh "$TARGETARCH" && rm /tmp/install-tools.sh
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
WORKDIR /opt/greenops-starter
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o /usr/local/bin/greenops-static ./examples/go-static \
    && python -m unittest discover -s tests -v \
    && terraform -chdir=examples/terraform init -backend=false \
    && terraform -chdir=examples/terraform validate \
    && exo version && terraform version && go version && python --version
WORKDIR /workspace
CMD ["bash"]
