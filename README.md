# PHP 7.4 emergency backport image

PHP **7.4.33 CLI + FPM** with the PHP security team's emergency backport for
**CVE-2026-109618** and **CVE-2026-109619**, built on Alpine 3.16 for
`linux/amd64` and `linux/arm64`. Includes the standard `docker-php-*` helpers.

This is an emergency bridge. Both PHP 7.4 and Alpine 3.16 are unsupported.
Upstream describes this backport as a minimal mitigation for an EOL version.
It does not provide the security maintenance of a supported PHP release.

## Use

```dockerfile
FROM ghcr.io/radito/php74-backport:7.4.33-fpm-alpine-backport1
```

Pin an image digest for deployments. The GHCR package currently requires
authentication and package access; repository visibility and package visibility
are separate. You can also build from this public source without GHCR access.

FPM listens on port 9000 using the default `www-data` pool. Install
application-specific extensions such as `pdo_mysql`, `zip`, `gd`, and `redis`
in your own Dockerfile. Composer and application dependencies are not included.

## Build and test

```sh
docker build -t php74-backport:test .
python3 tests/smoke.py php74-backport:test
```

GitHub Actions builds and tests both architectures before publishing shared
image tags. Tests cover CLI/FPM startup, sessions, form and multipart parsing,
and FPM availability after bounded memory exhaustion. Test scripts are excluded
from the image. Published images include build provenance and an SBOM.

## Source and behavior

- [Official PHP advisory](https://www.php.net/archive/2026.php#2026-10-21-5)
- [Official backport commit](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)
- [Historical official Docker recipe](https://github.com/docker-library/php/blob/b9f17156020c3aef71df681b27684533529347a7/7.4/alpine3.16/fpm/Dockerfile)

The source tarball and vendored patch have pinned SHA256 checksums. The build
applies the patch with zero fuzz and checks that its reverse applies before
compilation. Source and patch metadata are recorded in
`/usr/local/share/php-backport/build-info.json`.

The `PHP-7.4-CVE-2026-109618-109619` branch preserves upstream's backport source
and history. That branch reports `7.4.31-dev`; the image instead applies its
security patch to the PHP **7.4.33 release source**.

Upstream's backport disables session upload-progress tracking and immediately
terminates a process on PHP memory exhaustion. Applications depending on those
features need integration testing. These smoke tests do not prove absence of
all vulnerabilities or replace application testing before production rollout.
