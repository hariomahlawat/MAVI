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
