# Third-party components

The toolchain bundles Exoscale CLI 1.95.6 (Apache-2.0), egoscale v3.1.40 (Apache-2.0), Python exoscale 0.16.3 (ISC) and Terraform 1.13.4 (Business Source License 1.1), plus Go, Python and Debian packages under their respective licenses. The image is a hackathon development toolchain, not a claim that all bundled software shares one license. Retain their notices when redistributing.

Official projects and license references:

- https://github.com/exoscale/cli/tree/v1.95.6
- https://github.com/exoscale/egoscale/tree/v3.1.40
- https://github.com/exoscale/python-exoscale
- https://github.com/hashicorp/terraform/blob/v1.13.4/LICENSE

Archive checksums were obtained from the official release files on 20 October 2026. CLI linux/amd64: `5808b1e034244e5458081c58d013e85255df74e6119dca21c4404275f87213a6`; linux/arm64: `ae947c8d03ab953084188fd27a37c5761234788bb38761de6ee70bb002012c76`. Terraform linux/amd64: `98aa516201e948306698efd9954ab4cc0d1227c2578ba56245898b5f679e590b`; linux/arm64: `a17bde150a4d6c9e7ece063ab634c07723b8242e078f3ae9017486277d6690c4`.

Electricity/power/performance values are fictional game values. API response numbers in the guide are invented illustrations, not measured product/environmental claims. The public starter contains no electricity actual/forecast time series.

Feint (https://github.com/stephrobert/feint), Apache-2.0, provides the platform's
Exoscale protocol emulation basis. GreenOps integrates it behind run-scoped
authentication and an authoritative simulator. No Feint process runs inside this
toolchain image; the starter calls the challenge service.
