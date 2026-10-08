import pytest

import core.memory_sampling as sampling
from test_memory_parent_snapshot import setup
from test_memory_sampling import fixture


def test_nested_phases_are_separate_and_bounded_by_membership(monkeypatch, tmp_path):
    _, calls, scopes = setup(monkeypatch, tmp_path)
    scopes.profile_timings = True
    sample = scopes.snapshot()
    profile = sample['timing_profile']
    assert profile['version'] == sampling.PROFILE_VERSION == 'collector-phase-v3'
    nested = profile['membership_phases']
    assert [p['phase'] for p in nested] == [
        'root_identity', 'parent_snapshot', 'parent_index', 'tree_build',
        'member_identity_recheck', 'runner_membership',
        'console_host_verification', 'overlap_check']
    outer = next(p for p in profile['phases'] if p['phase'] == 'membership')
    assert all(outer['start'] <= p['start'] <= p['end'] <= outer['end'] for p in nested)
    assert all(p['completed'] and p['thread_cpu_seconds'] >= 0 for p in nested)
    assert all(a['end'] <= b['start'] for a, b in zip(nested, nested[1:]))
    assert sum(p['wall_seconds'] for p in nested) <= outer['wall_seconds']
    assert len(calls) == 2
    assert sample['scopes']['runner']['rss_bytes'] == 800


def test_legacy_backend_records_actual_children_path_only():
    p = fixture()
    scopes = sampling.ProcessScopes(1, 2, 3, p.__getitem__, profile_timings=True)
    names = [x['phase'] for x in scopes.snapshot()['timing_profile']['membership_phases']]
    assert names == ['root_identity', 'legacy_children', 'runner_membership',
                     'console_host_verification', 'overlap_check']


def test_new_backend_off_does_not_read_cpu_or_make_nested_records(monkeypatch, tmp_path):
    _, calls, scopes = setup(monkeypatch, tmp_path)
    def forbidden(): pytest.fail('profiling clock used while OFF')
    monkeypatch.setattr(sampling.time, 'thread_time', forbidden)
    sample = scopes.snapshot()
    assert 'timing_profile' not in sample and 'error' not in sample
    assert len(calls) == 2


@pytest.mark.parametrize('stage', ['root_identity', 'parent_snapshot', 'parent_index',
    'tree_build', 'member_identity_recheck', 'runner_membership',
    'console_host_verification', 'overlap_check'])
def test_failed_nested_stage_preserves_error_and_outer_failure(monkeypatch, tmp_path, stage):
    p, _, scopes = setup(monkeypatch, tmp_path)
    scopes.profile_timings = True
    if stage == 'root_identity': p[3].created += 1
    if stage == 'parent_snapshot':
        def fail(): raise sampling.MeasurementError('snapshot failed')
        scopes.parent_map_factory = fail
    if stage == 'parent_index':
        scopes.parent_map_factory = lambda: {2: 0, 3: 2, 4: 2, 5: 3}
    if stage == 'tree_build': p[5].created = 1
    if stage == 'member_identity_recheck':
        count = []
        def changed():
            count.append(1)
            return 105 if len(count) == 1 else 106
        p[5].create_time = changed
    if stage == 'runner_membership': p[3].parent = 99
    if stage == 'console_host_verification': p[4].path = tmp_path / 'fake.exe'
    if stage == 'overlap_check':
        p[1].parent = 3
        p[1].created = 110
        scopes.identities['web'] = 110
    sample = scopes.snapshot()
    assert sample['error']
    assert all(v['rss_bytes'] is None for v in sample['scopes'].values())
    profile = sample['timing_profile']
    failed = [x for x in profile['membership_phases'] if not x['completed']]
    assert len(failed) == 1 and failed[0]['phase'] == stage
    assert profile['phases'][0]['phase'] == 'membership'
    assert not profile['phases'][0]['completed']
    # Each snapshot owns its records, even after a failed one.
    original = sampling.ProcessScopes.members
    scopes.members = lambda records=None, parent_records=None: original(scopes, records, parent_records)
    again = scopes.snapshot()['timing_profile']['membership_phases']
    assert again is not profile['membership_phases']


def test_nested_context_records_independent_wall_and_cpu_on_error(monkeypatch):
    wall, cpu = iter([10., 10.5]), iter([2., 2.03])
    monkeypatch.setattr(sampling.time, 'perf_counter', lambda: next(wall))
    monkeypatch.setattr(sampling.time, 'thread_time', lambda: next(cpu))
    records = []
    with pytest.raises(sampling.MeasurementError):
        with sampling.ProcessScopes._phase(records, 'tree_build'):
            raise sampling.MeasurementError('invalid tree')
    assert records[0]['wall_seconds'] == pytest.approx(.5)
    assert records[0]['thread_cpu_seconds'] == pytest.approx(.03)
    assert not records[0]['completed']
