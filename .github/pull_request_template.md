## Change summary

<!-- What changed and why? -->

## Validation

- [ ] Relevant build/tests pass locally
- [ ] `python tools/verify_repo.py` passes
- [ ] Exact-head CI is green or remaining external qualification is explicitly identified

## Dependency / offline impact

- [ ] This PR adds or changes **no** library, SDK, native binary, runtime, model, database extension or OS prerequisite

**OR, if it does:**

- [ ] The dependency is justified; existing platform/framework capability was considered
- [ ] `config/dependencies/offline-dependency-policy-v1.json` is updated
- [ ] Package/lock files are updated
- [ ] Disconnected Development cache/staging is updated
- [ ] Production/offline bundle/runtime lock is updated where applicable
- [ ] MAVI Setup/readiness checks are updated if the target machine needs a new prerequisite
- [ ] Native/external payload version/hash/viability checks are included
- [ ] Required licences/notices are retained
- [ ] Relevant disconnected/hardware/update/recovery qualification is updated
- [ ] Affected runbooks/docs are updated

## Operator impact

- [ ] Normal Development remains one-click through `Setup-MAVI-Development.cmd`
- [ ] Normal Production remains one-click through `Setup-MAVI-Production.cmd`
- [ ] No new manual PATH edits, package-manager commands, pgAdmin steps, first-run downloads, CDN/cloud calls, online activation or telemetry dependency were introduced

## Documentation

<!-- List the docs/ADRs/runbooks updated, or explain why none are required. -->
