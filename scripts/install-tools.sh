#!/bin/sh
set -eu
arch="${1:?usage: install-tools.sh amd64|arm64}"
case "$arch" in
  amd64)
    exo_sha=5808b1e034244e5458081c58d013e85255df74e6119dca21c4404275f87213a6
    tf_sha=98aa516201e948306698efd9954ab4cc0d1227c2578ba56245898b5f679e590b ;;
  arm64)
    exo_sha=ae947c8d03ab953084188fd27a37c5761234788bb38761de6ee70bb002012c76
    tf_sha=a17bde150a4d6c9e7ece063ab634c07723b8242e078f3ae9017486277d6690c4 ;;
  *) echo 'Unsupported architecture' >&2; exit 1 ;;
esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL --retry 3 "https://github.com/exoscale/cli/releases/download/v1.95.6/exoscale-cli_1.95.6_linux_${arch}.tar.gz" -o "$work/exo.tgz"
printf '%s  %s\n' "$exo_sha" "$work/exo.tgz" | sha256sum -c -
tar -xzf "$work/exo.tgz" -C "$work"
install -m 0755 "$work/exo" /usr/local/bin/exo
mkdir -p /usr/share/doc/exo /usr/share/doc/terraform
cp "$work/LICENSE" /usr/share/doc/exo/LICENSE
curl -fsSL --retry 3 "https://releases.hashicorp.com/terraform/1.13.4/terraform_1.13.4_linux_${arch}.zip" -o "$work/terraform.zip"
printf '%s  %s\n' "$tf_sha" "$work/terraform.zip" | sha256sum -c -
mkdir "$work/terraform"
unzip -q "$work/terraform.zip" -d "$work/terraform"
install -m 0755 "$work/terraform/terraform" /usr/local/bin/terraform
cp "$work/terraform/LICENSE.txt" /usr/share/doc/terraform/LICENSE.txt
