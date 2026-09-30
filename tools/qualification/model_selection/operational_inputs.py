"""Frozen host and 500-camera envelope checks for the bounded S2c projection."""
from __future__ import annotations

from .canonical import canonical, digest, integer, keys, require, text, tokens
from .job_replay import instant


def host_profile(profile: dict, experiment: dict) -> None:
    keys(profile, {'schema','hostClassId','cpuModel','physicalCores','logicalCores','smtEnabled','ramBytes',
                   'osVersion','storage','apiPlacement','coResidentIdentities','threadSettings',
                   'workerProcessCounts','powerPolicy','runtimeFamily','runtimeManifestSha256'}, 'hostProfile')
    require(profile['schema'] == 'mavi-s2c-host-profile-v1' and profile['hostClassId'] == experiment['hostClassId'], 'hostProfile:identity')
    for k in ('cpuModel','osVersion','apiPlacement','powerPolicy','runtimeFamily'): text(profile[k], 'hostProfile:'+k)
    for k in ('physicalCores','logicalCores','ramBytes'): integer(profile[k], 'hostProfile:'+k, 1)
    require(type(profile['smtEnabled']) is bool and profile['logicalCores'] >= profile['physicalCores'], 'hostProfile:cores')
    require(profile['smtEnabled'] or profile['logicalCores'] == profile['physicalCores'], 'hostProfile:SMT')
    keys(profile['storage'], {'kind','readBytesPerSecond','writeBytesPerSecond'}, 'hostProfile:storage')
    text(profile['storage']['kind'], 'storage:kind')
    for k in ('readBytesPerSecond','writeBytesPerSecond'): integer(profile['storage'][k], k, 1)
    keys(profile['threadSettings'], {'inferenceThreads','runtimeThreads','decodeThreads'}, 'hostProfile:threads')
    for k, v in profile['threadSettings'].items(): integer(v, k, 1)
    tokens(profile['coResidentIdentities'], 'coResidentIdentities')
    for v in profile['coResidentIdentities']: digest(v, 'coResidentIdentity')
    counts = profile['workerProcessCounts']
    require(type(counts) is list and bool(counts), 'hostProfile:processCounts')
    for v in counts: integer(v, 'workerProcessCount', 1)
    require(counts == sorted(set(counts)) and experiment['workersPerHost'] in counts, 'hostProfile:frozen_topology')
    digest(profile['runtimeManifestSha256'], 'runtimeManifestSha256')
    require(experiment['limits']['maxRamBytesPerHost'] <= profile['ramBytes'], 'hostProfile:RAM_limit')


def job_service_shape(job: dict) -> dict:
    """Exact finite payload covered by a measured whole-job service shape."""
    for c in ('person','vehicle'): integer(job[c+'Tracks'], c+'Tracks')
    tracks = job['personTracks']+job['vehicleTracks']
    require(tracks <= 10_000, 'envelope:job_Track_bound')
    crops = job['cropsPerTrack']
    keys(crops, {'person','vehicle'}, 'envelope:crops')
    for c, counts in crops.items():
        require(type(counts) is list and len(counts) == job[c+'Tracks'], 'envelope:crops_per_Track_population')
        for count in counts: integer(count, 'envelope:crop_count')
        require(counts == sorted(counts), 'envelope:crop_counts_order')
    integer(job['evidenceSetBytes'], 'envelope:evidence_bytes')
    return {k: job[k] for k in ('personTracks','vehicleTracks','cropsPerTrack','evidenceSetBytes')}


def service_coverage(coverage: dict, workloads: list[dict]) -> None:
    """No service time may be extrapolated to an unmeasured payload signature."""
    expected = {}
    for w in workloads:
        for job in w['jobs']:
            expected.setdefault(job['shape'], set()).add(canonical(job_service_shape(job)))
    keys(coverage, set(expected), 'serviceCoverage')
    for shape, signatures in expected.items():
        rows = coverage[shape]
        require(type(rows) is list and bool(rows), 'serviceCoverage:list')
        for row in rows:
            keys(row, {'personTracks','vehicleTracks','cropsPerTrack','evidenceSetBytes'}, 'serviceCoverage:shape')
            job_service_shape(row)
        actual = [canonical(row) for row in rows]
        require(actual == sorted(set(actual)) and set(actual) == signatures, 'serviceCoverage:unmeasured_job_shape')


def workload_envelope(envelope: dict, workloads: list[dict]) -> None:
    keys(envelope, {'targetCameraCount','cameraClasses','correlatedBusyPeriods','releaseCadenceUs','runDurationUs',
                    'jobsPerInterval','tracksPerJob','cropsPerTrack','evidenceSetBytes','initialBacklog',
                    'burstWorkloadIds','failureWorkloadIds','drainLimitUs','storageLimitBytes','apiMaxRequestsPerSecond'}, 'workloadEnvelope')
    integer(envelope['targetCameraCount'], 'cameraCount', 1)
    require(envelope['targetCameraCount'] == 500, 'envelope:500_target')
    for k in ('releaseCadenceUs','runDurationUs','drainLimitUs','storageLimitBytes','apiMaxRequestsPerSecond'): integer(envelope[k], k, 1)
    integer(envelope['initialBacklog'], 'initialBacklog')
    require(type(envelope['cameraClasses']) is list and bool(envelope['cameraClasses']), 'cameraClasses:list')
    ids=[]
    for row in envelope['cameraClasses']:
        keys(row, {'classId','proportionPpm','description'}, 'cameraClass')
        ids.append(text(row['classId'], 'cameraClass:id'))
        integer(row['proportionPpm'], 'proportionPpm', 1); text(row['description'], 'cameraClass:description')
    require(ids == sorted(set(ids)) and sum(r['proportionPpm'] for r in envelope['cameraClasses']) == 1_000_000, 'cameraClasses:proportions')
    keys(envelope['jobsPerInterval'], set(ids), 'jobsPerInterval')
    for v in envelope['jobsPerInterval'].values(): integer(v, 'jobsPerInterval')
    require(sum(envelope['jobsPerInterval'].values()) > 0, 'envelope:no_releases')
    require(type(envelope['correlatedBusyPeriods']) is list, 'busyPeriods:list')
    for row in envelope['correlatedBusyPeriods']:
        keys(row, {'startOffsetUs','endOffsetUs','classes'}, 'busyPeriod')
        integer(row['startOffsetUs'], 'startOffsetUs'); integer(row['endOffsetUs'], 'endOffsetUs')
        tokens(row['classes'], 'busyPeriod:classes', nonempty=True)
        require(set(row['classes']) <= set(ids) and row['startOffsetUs'] < row['endOffsetUs'] <= envelope['runDurationUs'], 'busyPeriod:range')
    keys(envelope['tracksPerJob'], {'person','vehicle'}, 'tracksPerJob')
    for label, bins in list(envelope['tracksPerJob'].items())+[('cropsPerTrack',envelope['cropsPerTrack']),('evidenceSetBytes',envelope['evidenceSetBytes'])]:
        require(type(bins) is list and bool(bins), label+':bins')
        previous=-1
        for row in bins:
            keys(row, {'minimum','maximum','count'}, label+':bin')
            for k in row: integer(row[k], label+':'+k)
            require(previous < row['minimum'] <= row['maximum'] and row['count'] > 0, label+':ordered_bins')
            previous=row['maximum']
        if label in ('person','vehicle'): require(previous <= 10_000, 'tracks:10k_bound')
    for key, role in (('burstWorkloadIds','small-burst'),('failureWorkloadIds','recovery')):
        tokens(envelope[key], key, nonempty=True)
        require(envelope[key] == sorted(w['workloadId'] for w in workloads if w['role'] == role), key+':required_traces')
    periods=(envelope['runDurationUs']+envelope['releaseCadenceUs']-1)//envelope['releaseCadenceUs']
    require(periods*sum(envelope['jobsPerInterval'].values()) <= 100_000, 'envelope:bounded_releases')
    for w in workloads:
        for job in w['jobs']:
            keys(job, {'id','shape','queuedAtUtc','identitySha256','personTracks','vehicleTracks',
                       'cropsPerTrack','evidenceSetBytes'}, 'envelope:job')
            job_service_shape(job)
            for label, values in (('cropsPerTrack',[n for counts in job['cropsPerTrack'].values() for n in counts]), ('evidenceSetBytes',[job['evidenceSetBytes']])):
                require(all(any(b['minimum'] <= value <= b['maximum'] for b in envelope[label]) for value in values), 'envelope:payload_distribution')
        if w['role'] != '500-camera': continue
        start=instant(w['startAtUtc'], 'startAtUtc')
        require(instant(w['endAtUtc'],'endAtUtc')-start == envelope['runDurationUs'], 'envelope:horizon')
        queued=[instant(j['queuedAtUtc'],'queuedAtUtc') for j in w['jobs']]
        require(sum(t < start for t in queued) == envelope['initialBacklog'], 'envelope:initial_backlog')
        expected={(start+offset, cid): count for offset in range(0,envelope['runDurationUs'],envelope['releaseCadenceUs']) for cid,count in envelope['jobsPerInterval'].items() if count}
        actual={}
        for j,t in zip(w['jobs'],queued):
            if t < start: continue
            key=(t,j['shape']); actual[key]=actual.get(key,0)+1
        require(actual == expected, 'envelope:release_trace_mismatch')
        # Histograms describe each entire 500-camera trace, including backlog.
        populations = [(c,[j[c+'Tracks'] for j in w['jobs']],bins) for c,bins in envelope['tracksPerJob'].items()]
        populations += [('cropsPerTrack',[n for j in w['jobs'] for counts in j['cropsPerTrack'].values() for n in counts],envelope['cropsPerTrack']),
                        ('evidenceSetBytes',[j['evidenceSetBytes'] for j in w['jobs']],envelope['evidenceSetBytes'])]
        for label, values, bins in populations:
            counts = [sum(b['minimum'] <= value <= b['maximum'] for value in values) for b in bins]
            require(sum(counts) == len(values) and counts == [b['count'] for b in bins], 'envelope:histogram_count:'+label)
        for period in envelope['correlatedBusyPeriods']:
            synchronized = [t for t,_ in actual if start+period['startOffsetUs'] <= t < start+period['endOffsetUs']
                            and all(actual.get((t,c),0) > 0 for c in period['classes'])]
            require(bool(synchronized), 'envelope:busy_period_unrepresented')
