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
