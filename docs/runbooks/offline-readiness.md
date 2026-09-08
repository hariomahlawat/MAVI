# Offline Readiness Runbook

Every major milestone should be exercised on a test machine with Internet access disabled.

Verify that:

1. the operational API starts without external connectivity;
2. the React UI loads with all fonts, scripts, styles and images local;
3. authentication does not call an external identity provider;
4. the Python worker starts without downloading packages or model weights;
5. model files are resolved from approved local storage;
6. video processing, search and evidence retrieval function on the LAN;
7. logs contain no failed Internet telemetry or licence-check calls;
8. backup and restore use only local/approved network storage;
9. an update can be applied from a controlled offline bundle.
