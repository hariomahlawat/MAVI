"""Frozen host and 500-camera envelope checks for the bounded S2c projection."""
from __future__ import annotations

from .canonical import digest, integer, keys, require, text, tokens
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
            for c in ('person','vehicle'):
                require(any(b['minimum'] <= j[c+'Tracks'] <= b['maximum'] for b in envelope['tracksPerJob'][c]), 'envelope:Track_distribution')
        require(actual == expected, 'envelope:release_trace_mismatch')
