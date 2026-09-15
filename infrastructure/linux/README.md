# Linux Vision Deployment

Target role: Python/CUDA vision workers on Ubuntu/Linux servers. The worker loads approved model artifacts from local controlled storage and must not download models at runtime.

## Task-12 CPU bundle

The qualified hosted CPU baseline uses:

~~~text
platform variant: linux-x86_64-cpu
Python: CPython 3.12.14
~~~

Provision CPython `3.12.14` before consuming the bundle. Install only from the supplied wheelhouse and lock using the command in `infrastructure/offline-bundle/README.md` / bundle `INSTALL.txt`.

The Task-12 bundle is a `qualification-candidate` until Task 14 completes formal disconnected-install, CUDA hardware, recovery, CCTV quality and production-performance qualification.

Do not infer Linux CUDA support from the CPU bundle. `linux-x86_64-cuda` remains pending hardware qualification and must receive its own qualified wheel lock after the CUDA environment is frozen.

Runtime release files remain local and read-only inside the deployment boundary. No package-index, model-hub or first-run download fallback is permitted.


## Future runtime dependencies

A new Python/native/CUDA/model dependency is not complete when it merely imports on a connected workstation. Update `config/dependencies/offline-dependency-policy-v1.json`, the applicable platform lock/wheelhouse/runtime bundle, licence/provenance records and disconnected qualification in the same feature.

Follow `docs/architecture/dependency-and-offline-packaging-policy.md`. Runtime package-index, model-hub, first-run download and silent CPU fallback remain prohibited.
