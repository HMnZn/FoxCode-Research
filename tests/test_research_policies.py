"""Mechanism tests with fixed evidence; these are not effectiveness experiments."""
import json
import sqlite3
import time

import pytest
from fox_ai.src import AssistantMessage, Context, ToolCall, ToolResultMessage, Usage, UserMessage
from fox_coding_agent.src import CodingAgent, Config, ContextManager
from fox_coding_agent.src.context.compressor import groups, compact_observation
from fox_coding_agent.src.context.scorer import score
from fox_coding_agent.src.memory import MemoryStore, retrieve
from fox_coding_agent.src.memory.store import fingerprint_files
from fox_coding_agent.src.skills import Skill, SkillEvolution, SkillStore, extract_experience


def candidate(**kwargs):
    return Skill('edit-recovery', 'Fix ambiguous Edit', 'Edit exact match failure',
                 'Read the file, choose unique old_text, then Edit and verify.',
                 tags=['Edit'], source_trajectory=['extraction'], **kwargs)


def test_protocol_groups_preserve_multiple_calls_and_reject_orphans():
    calls = [ToolCall('a', 'Read', {}), ToolCall('b', 'Read', {})]
    messages = [AssistantMessage(tool_calls=calls), ToolResultMessage('b', 'Read', 'B'),
                ToolResultMessage('a', 'Read', 'A')]
    assert len(groups(messages)) == 1
    with pytest.raises(ValueError, match='incomplete'):
        groups(messages[:-1])
    with pytest.raises(ValueError, match='Orphan'):
        groups([messages[-1]])


def test_progressive_compression_keeps_evidence_and_does_not_mutate_raw():
    manager = ContextManager(1500)
    user = UserMessage('Fix parser; do not change public APIs')
    manager.state.user(user.content)
    call = ToolCall('a', 'Bash', {'command': 'pytest parser'})
    result = ToolResultMessage('a', 'Bash', 'source line\n' * 3000 + 'FAILED parser assertion\n' + 'tail\n' * 100, True)
    manager.state.tool(call, result)
    manager.state.artifacts['a'] = '.foxcode/research/observations/a.txt'
    context = Context([user, AssistantMessage(tool_calls=[call]), result])
    manager.prepare(context)
    compressed = next(m for m in context.messages if m.role == 'tool')
    assert 'FAILED parser assertion' in compressed.content
    assert 'observations/a.txt' in compressed.content
    assert len(result.content) > 10000 and len(compressed.content) < 1100
    assert manager.last['compacted_groups'] == 1
    assert manager.last['tokens'] <= manager.budget
    count = manager.compressions
    manager.prepare(context)
    assert manager.compressions == count  # Hysteresis avoids immediate re-compression.


def test_layer_budget_and_required_trial():
    manager = ContextManager(2000)
    manager.set_sources('base policy', [{'kind': 'memory', 'id': '1', 'score': 1, 'text': 'fact ' * 5000},
                                       {'kind': 'skill', 'id': 's', 'score': 2, 'text': 'Read before Edit'}])
    context = Context([UserMessage('fix')])
    manager.prepare(context)
    assert 'fact' not in context.system_prompt and 'Read before Edit' in context.system_prompt
    assert manager.last['retrieval_dropped'] == [{'kind': 'memory', 'id': '1'}]
    manager.set_sources('base', [{'kind': 'skill', 'id': 'trial', 'required': True, 'text': 'x' * 10000}])
    with pytest.raises(ValueError, match='Explicit trial'):
        manager.prepare(context)


def test_state_revision_and_estimator_calibration():
    manager = ContextManager(2000, context_window=2100, max_tokens=300)
    read = ToolCall('read', 'Read', {'file_path': 'a.py'})
    result = ToolResultMessage('read', 'Read', 'source')
    manager.state.tool(read, result)
    manager.state.tool(ToolCall('write', 'Write', {'file_path': 'a.py'}), ToolResultMessage('write', 'Write', 'ok'))
    assert 'Changed since last Read' in manager.state.summary()
    assert score(result, 0, 2, manager.state).stale_penalty < 0
    manager.prepare(Context([UserMessage('fix')]))
    manager.observe_usage(Usage(input_tokens=manager.last_estimate * 2))
    assert manager.calibration > 1 and manager.budget == 1800


def test_memory_dedup_conflicts_validity_and_invalidation(tmp_path):
    store = MemoryStore(tmp_path / 'memory.sqlite')
    first = store.add('Use pytest for parser', memory_type='semantic', scope='p', key='test-command', source='user')
    assert store.add('Use pytest for parser', memory_type='semantic', scope='p', key='test-command', source='user') == first
    second = store.add('Use unittest for parser', memory_type='semantic', scope='p', key='test-command', source='correction')
    assert store.get(first).status == 'superseded'
    assert store.get(second).supersedes == first and store.get(second).version == 2
    assert [h['memory']['id'] for h in retrieve(store, 'parser', 'p')] == [second]
    expires = store.add('parser ttl', scope='p', ttl_days=1)
    assert expires not in [h['memory']['id'] for h in retrieve(store, 'parser', 'p', now=time.time() + 2*86400)]
    store.invalidate(second, 'command no longer exists')
    assert not retrieve(store, 'unittest', 'p')
    store.close()


def test_memory_independent_support_and_file_freshness(tmp_path):
    (tmp_path / 'parser.py').write_text('v1')
    store = MemoryStore(tmp_path / 'memory.sqlite')
    metadata = {'file_fingerprints': fingerprint_files(tmp_path, ['parser.py'])}
    id = store.observe_fact('test', 'Run pytest parser', scope='p', source='t1', metadata=metadata)
    store.observe_fact('test', 'Run pytest parser', scope='p', source='t1', metadata=metadata)
    assert store.get(id).metadata['independent_support'] == 1
    assert not retrieve(store, 'parser', 'p')
    store.observe_fact('test', 'Run pytest parser', scope='p', source='t2', metadata=metadata)
    assert store.get(id).status == 'active'
    fresh = retrieve(store, 'parser', 'p', cwd=tmp_path)[0]
    (tmp_path / 'parser.py').write_text('v2')
    stale = retrieve(store, 'parser', 'p', cwd=tmp_path)[0]
    assert stale['stale_paths'] == ['parser.py'] and stale['score'] < fresh['score']
    store.close()


def test_memory_diversification_and_legacy_schema_migration(tmp_path):
    path = tmp_path / 'memory.sqlite'
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE memories(id INTEGER PRIMARY KEY,content TEXT NOT NULL,
        memory_type TEXT NOT NULL,scope TEXT NOT NULL,source TEXT NOT NULL,confidence REAL NOT NULL,
        success INTEGER NOT NULL,verify INTEGER NOT NULL,created_at REAL NOT NULL);
        CREATE VIRTUAL TABLE memory_fts USING fts5(content);''')
    db.execute('INSERT INTO memories VALUES (1,?,?,?,?,?,?,?,?)', ('pytest parser tests', 'semantic', 'p', 'user', .9, 1, 1, time.time()))
    db.execute("INSERT INTO memory_fts(rowid,content) VALUES(1,'pytest parser tests')")
    db.commit()
    db.close()
    store = MemoryStore(path)
    assert store.get(1).status == 'active' and store.get(1).fingerprint
    store.add('pytest parser tests extra', scope='p')
    different = store.add('parser encoding unicode fixture pytest', scope='p')
    hits = retrieve(store, 'pytest parser', 'p', top_k=2)
    assert len(hits) == 2 and different in [h['memory']['id'] for h in hits]
    store.close()


def test_serving_version_survives_candidate_and_feedback_is_versioned(tmp_path):
    store = SkillStore(tmp_path / 'skills.sqlite')
    evolution = SkillEvolution(store)
    skill = store.propose(candidate())
    for id in ('t1', 't2'):
        store.record(skill.name, success=True, evidence_id=id)
    assert store.serving(skill.name).version == 1
    revised = candidate()
    revised.instructions += ' Run focused tests.'
    revised.source_trajectory = ['new-extraction']
    revised = store.propose(revised)
    assert revised.version == 2 and revised.status == 'candidate'
    assert store.retrieve('Edit')[0].version == 1
    evolution.validate(skill.name, {'id': 'old-trial', 'status': 'completed', 'used_skills': [skill.name],
                                  'used_skill_versions': {skill.name: 1}}, useful=True)
    assert store.get(skill.name, 1).success_count == 3 and store.get(skill.name, 2).success_count == 0
    with pytest.raises(ValueError, match='Version-specific'):
        evolution.validate(skill.name, {'id': 'legacy-trial', 'status': 'completed'}, useful=True)
    for id in ('new1', 'new2'):
        evolution.validate(skill.name, {'id': id, 'status': 'completed', 'used_skills': [skill.name],
                                      'used_skill_versions': {skill.name: 2}}, useful=True)
    assert store.serving(skill.name).version == 2
    store.rollback(skill.name, 1, reason='external regression report')
    assert store.retrieve('Edit')[0].version == 1
    assert len(store.history(skill.name)['versions']) == 2
    assert store.history(skill.name)['events'][-1]['action'] == 'rollback'
    store.close()
    store = SkillStore(tmp_path / 'skills.sqlite')
    assert store.serving(skill.name).version == 1  # Reopening must preserve explicit rollback.
    store.close()


def test_skill_usage_is_not_validation_and_environment_gates(tmp_path):
    store = SkillStore(tmp_path / 'skills.sqlite')
    skill = store.propose(candidate(scope='p', environment={'shell': 'powershell'}))
    for id in ('1', '2'):
        store.record(skill.name, success=True, evidence_id=id)
    assert not store.retrieve('Edit', scope='other', environment={'shell': 'powershell'})
    assert not store.retrieve('Edit', scope='p', environment={'shell': 'cmd.exe'})
    assert store.retrieve('Edit', scope='p', environment={'shell': 'powershell'})
    for _ in range(3):
        store.mark_usage(skill.name, 1, 'task', 'injected')
    current = store.get(skill.name)
    assert current.injected_count == 1 and current.success_count == 2
    assert 0 < current.confidence_lower < current.confidence
    store.close()


def test_delayed_feedback_and_unrelated_bash_success(tmp_path):
    store = SkillStore(tmp_path / 'skills.sqlite')
    evolution = SkillEvolution(store)
    failed = {'call': {'id': 'a', 'name': 'Bash', 'arguments': {'command': 'pytest parser'}},
              'result': {'is_error': True, 'content': 'FAILED parser'}}
    unrelated = {'call': {'id': 'b', 'name': 'Bash', 'arguments': {'command': 'echo ok'}},
                 'result': {'is_error': False, 'content': 'ok'}}
    trajectory = {'id': 'old', 'scope': 'p', 'prompt': 'fix parser', 'status': 'completed', 'tools': [failed, unrelated]}
    assert not extract_experience(trajectory)
    evolution.observe(trajectory)
    correction = evolution.consume_feedback('p', '纠正：必须先检查当前 shell，再设置环境变量', 'next')
    assert correction.source_trajectory == ['old', 'next']
    assert correction.experiences[0]['trajectory_id'] == 'old'
    assert evolution.consume_feedback('p', '纠正：again', 'third') is None
    with pytest.raises(ValueError, match='held-out'):
        store.record(correction.name, success=True, evidence_id='next')
    store.close()


async def test_coding_agent_archives_observations_and_records_injection_version(tmp_path):
    from fox_ai.src import Done

    coding = CodingAgent(Config(cwd=tmp_path, model='fake'), stream_fn=None)
    skill = coding.skills.propose(candidate())
    calls = 0

    async def model(model, context, options):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield Done(AssistantMessage(tool_calls=[ToolCall('read', 'Read', {'file_path': 'large.py'})]))
        else:
            yield Done(AssistantMessage('inspected'))

    coding.agent.stream_fn = model
    (tmp_path / 'large.py').write_text('large original source line\n' * 1000)
    events = [event async for event in coding.run('Inspect the file', trial_skill=skill.name)]
    assert events[-1].data['status'] == 'completed'
    assert coding.trajectory['used_skill_versions'] == {skill.name: 1}
    assert coding.trajectory['learn'] is False
    assert coding.memory.counts() == {}  # Held-out trial does not feed the memory corpus.
    step = coding.trajectory['tools'][0]
    assert (tmp_path / step['artifact']).read_text() == step['result']['content']
    persisted = json.loads((coding.config.data_dir / 'trajectories.jsonl').read_text())
    assert 'context_audit' in persisted and 'skill_evolution' in persisted
    assert coding.skills.get(skill.name).success_count == 0
    coding.close()


def test_policy_constraints_require_revision_and_legacy_skills_are_preserved(tmp_path):
    path = tmp_path / 'skills.sqlite'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE skills(name TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    db.execute('INSERT INTO skills VALUES (?,?)', ('legacy', json.dumps({
        'name': 'legacy', 'description': 'Edit recovery', 'trigger': 'Edit failure',
        'instructions': 'Read before Edit', 'status': 'active', 'success_count': 2, 'confidence': .75,
        'source_trajectory': ['origin'],
    })))
    db.commit()
    db.close()
    store = SkillStore(path)
    original = store.serving('legacy')
    assert original.version == 1 and store.history('legacy')['versions'][0]['instructions'] == 'Read before Edit'
    changed = store.get('legacy')
    changed.preconditions = ['Only when matching unique old_text']
    with pytest.raises(ValueError, match='immutable'):
        store.save(changed)
    revised = store.propose(changed)
    assert revised.version == 2 and revised.success_count == 0
    assert store.serving('legacy').version == 1
    store.close()


def test_recovery_generalizes_resource_without_revision_churn(tmp_path):
    store = SkillStore(tmp_path / 'skills.sqlite')
    evolution = SkillEvolution(store)
    for task, path in [('one', 'a.py'), ('two', 'b.py')]:
        trajectory = {'id': task, 'scope': 'p', 'status': 'completed', 'prompt': 'fix Edit', 'tools': [
            {'call': {'id': task+'-fail', 'name': 'Edit', 'arguments': {'file_path': path, 'old_text': 'missing'}},
             'result': {'is_error': True, 'content': 'old_text must occur exactly once'}},
            {'call': {'id': task+'-ok', 'name': 'Edit', 'arguments': {'file_path': path, 'old_text': 'unique'}},
             'result': {'is_error': False, 'content': 'edited'}},
        ]}
        evolution.observe(trajectory)
    skills = store.all()
    assert len(skills) == 1 and skills[0].version == 1
    assert len(skills[0].experiences) == 2 and skills[0].success_count == 0
    assert 'a.py' not in skills[0].trigger and 'b.py' not in skills[0].instructions
    store.close()


async def test_learning_disabled_preserves_trajectory_without_new_knowledge(tmp_path):
    from fox_ai.src import Done

    async def model(*args):
        yield Done(AssistantMessage('acknowledged'))

    coding = CodingAgent(Config(cwd=tmp_path, model='fake'), stream_fn=model)
    events = [event async for event in coding.run('纠正：必须先检查当前 shell', learn=False)]
    assert events[-1].data['status'] == 'completed'
    assert not coding.skills.all() and coding.evolution.snapshot()['pending_scopes'] == 0
    assert json.loads((coding.config.data_dir / 'trajectories.jsonl').read_text(encoding='utf-8'))['learn'] is False
    coding.close()
