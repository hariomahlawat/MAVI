# ADR-003: Online Development, Offline-by-Design Production

**Status:** Accepted  
**Date:** 2026-09-08

## Decision

Development may use Internet-connected tooling, package registries, coding agents, public datasets and model repositories. Production installation and operation must require no Internet connectivity.

## Required properties

- all application and UI assets are local;
- all AI models run locally;
- authentication is local to the deployment boundary;
- model weights are imported through controlled release bundles;
- no runtime cloud API, CDN, telemetry or online licence dependency exists;
- offline installation, backup, restore and update procedures are testable.
