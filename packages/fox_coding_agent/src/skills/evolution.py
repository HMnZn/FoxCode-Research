"""Extractor -> conservative maintainer -> candidates; effectiveness stays external."""
import hashlib
import json
import re
from dataclasses import replace
from .store import Skill


CORRECTION = re.compile(r'\s*(?:纠正[：:]|不对[，,:：]|你错了|correction:|actually[, :])', re.I)


def _redact(text):
    text = re.sub(r'(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1<redacted>', text)
    return re.sub(r'\bsk-[a-zA-Z0-9_-]{8,}', '<redacted>', text)


def _cause(error):
    for pattern, label in [(r'not found|no such file|FileNotFound', 'missing-resource'),
                           (r'exactly once|unique|old_text|match', 'edit-mismatch'),
                           (r'not recognized|export|syntax', 'shell-syntax'),
                           (r'timeout|timed out', 'timeout'),
                           (r'permission|denied', 'permission'),
                           (r'FAILED|AssertionError', 'test-failure')]:
        if re.search(pattern, error, re.I):
            return label
    # Unknown error types remain distinct; do not merge arbitrary failures.
    return hashlib.sha256(re.sub(r'\d+|[\'"].*?[\'\"]', '', error[:160]).encode()).hexdigest()[:10]


def _resource(call):
    if call['name'] != 'Bash':
        return str(call['arguments'].get('file_path', call['arguments'].get('pattern', '')))
    command = str(call['arguments'].get('command', ''))
    if re.search(r'\bexport\b|\$env:|\bset\s+\w+=', command, re.I):
        return 'shell-environment'
    for family in ('pytest', 'unittest', 'npm', 'tsc', 'git', 'pip', 'uv'):
        if re.search(r'\b' + family + r'\b', command):
            return family
    return (re.findall(r'[\w.-]+', command) or ['unknown'])[0]


def _arguments(call):
    args = call['arguments']
    return {k: _redact(str(v))[:240] if k in {'command', 'file_path', 'pattern'} else
            f'<{type(v).__name__}, length={len(str(v))}>' for k, v in args.items()}


def _candidate(trajectory, call, failed, recovery=None, *, kind='recovery'):
    cause = _cause(failed['result']['content'])
    family = f"{kind}:{call['name']}:{cause}"
    identity = family + trajectory.get('scope', '') + json.dumps(trajectory.get('environment', {}), sort_keys=True)
    name = ('recover-' if recovery else 'repeated-') + hashlib.sha256(identity.encode()).hexdigest()[:12]
    recipes = {
        'edit-mismatch': ['Read the current target file before editing.',
                          'Choose an exact old_text that occurs once; include surrounding lines to disambiguate.',
                          'Apply the focused Edit, re-read the changed region, and run the relevant check.'],
        'shell-syntax': ['Identify the shell actually executing the command.',
                         'Use environment assignment and quoting supported by that shell.',
                         'Retry the smallest command and inspect its return code before continuing.'],
        'missing-resource': ['Use Glob to verify the resource path relative to the project.',
                             'Read the discovered file and adjust the original operation to the current layout.',
                             'Check the intended resource rather than assuming historical paths still exist.'],
        'test-failure': ['Inspect the failing test, traceback, and the affected implementation.',
                         'Make one change consistent with the failure evidence.',
                         'Re-run the same test target, then inspect the test output and exit code.'],
    }
    procedure = recipes.get(cause, ['Inspect the specific tool failure and current environment.',
                                   'Change the strategy only after verifying the relevant preconditions.',
                                   'Re-run the original operation and validate the result.'])
    experience = {'kind': kind, 'trajectory_id': trajectory['id'], 'cause': cause,
                  'resource': _resource(call), 'failure_call_id': failed['call'].get('id'),
                  'failure': _redact(failed['result']['content'])[:400], 'failed_arguments': _arguments(failed['call']),
                  'recovery_call_id': recovery['call'].get('id') if recovery else None,
                  'successful_arguments': _arguments(recovery['call']) if recovery else None,
                  'causality': 'candidate_hypothesis'}
    trigger = f"{call['name']} {cause} in project {'commands' if call['name'] == 'Bash' else 'files'}"
    return Skill(name, f"Handle {call['name']} {cause} using verified preconditions", trigger,
                 '\n'.join(f'{i + 1}. {step}' for i, step in enumerate(procedure)),
                 tags=[call['name'], cause], source_trajectory=[trajectory['id']],
                 scope=trajectory.get('scope', ''), environment=trajectory.get('environment', {}),
                 preconditions=['Verify that the current failure matches the recorded cause.'],
                 procedure=procedure, verification=['Validate the original operation; tool success alone is not task success.'],
                 anti_patterns=['Do not blindly repeat identical failing arguments.', 'Do not reuse historical payload or credentials.'],
                 experiences=[experience], family=family)


def _correction(prompt, sources, scope='', environment=None):
    text = _redact(prompt)
    name = 'correction-' + hashlib.sha256(text.encode()).hexdigest()[:12]
    return Skill(name, text[:160], 'User-corrected coding behavior', text,
                 tags=['user-correction'], source_trajectory=sources, scope=scope,
                 environment=environment or {}, procedure=[text],
                 preconditions=['Confirm this is a durable instruction applicable to the current task.'],
                 verification=['Ask for held-out external feedback before treating the rule as validated.'],
                 experiences=[{'kind': 'user-correction', 'trajectory_id': sources[0], 'feedback_trajectory_id': sources[-1]}],
                 family='correction:' + name)


def extract_experience(trajectory):
    failures, repeated, candidates = {}, {}, []
    for index, step in enumerate(trajectory['tools']):
        call, result = step['call'], step['result']
        key = (call['name'], _resource(call))
        if result['is_error']:
            failures[key] = (index, step)
            signature = (key, _cause(result['content']))
            repeated[signature] = repeated.get(signature, 0) + 1
            if repeated[signature] == 2:
                candidates.append(_candidate(trajectory, call, step, kind='repeated-failure'))
            continue
        failed = failures.pop(key, None)
        if not failed or index - failed[0] > 8 or failed[1]['call']['arguments'] == call['arguments']:
            continue
        # Same resource/tool family and a bounded window reduce spurious Bash pairing.
        candidates.append(_candidate(trajectory, call, failed[1], step))
    prompt = trajectory.get('prompt', '')
    if CORRECTION.match(prompt):
        candidates.append(_correction(prompt, [trajectory['id']], trajectory.get('scope', ''), trajectory.get('environment')))
    return candidates


class SkillEvolution:
    def __init__(self, store):
        self.store = store
        self.last_decisions = []

    def maintain(self, candidate):
        """Exact family gates merging; lexical similarity alone never authorizes it."""
        existing = self.store.get(candidate.name)
        if existing is None and candidate.family:
            existing = next((s for s in self.store.all() if s.family == candidate.family
                             and s.scope == candidate.scope and s.environment == candidate.environment), None)
        if existing:
            candidate = replace(candidate, name=existing.name)
            if existing.instructions != candidate.instructions:
                # Preserve the old procedure while incorporating distinct durable steps.
                steps = list(dict.fromkeys((existing.procedure or [existing.instructions]) + candidate.procedure))[:8]
                if not steps:
                    return self._discard(candidate, 'No structured procedure to merge safely')
                candidate = replace(candidate, procedure=steps,
                                    instructions='\n'.join(f'{i + 1}. {step}' for i, step in enumerate(steps)),
                                    preconditions=list(dict.fromkeys(existing.preconditions + candidate.preconditions)),
                                    verification=list(dict.fromkeys(existing.verification + candidate.verification)),
                                    anti_patterns=list(dict.fromkeys(existing.anti_patterns + candidate.anti_patterns)))
            action = 'merge'
        else:
            action = 'add'
        if len(candidate.instructions) > 5000 or not candidate.instructions.strip():
            return self._discard(candidate, 'Candidate is empty or exceeds the reusable procedure budget')
        skill = self.store.propose(candidate)
        decision = {'action': action, 'name': skill.name, 'version': skill.version,
                    'source': candidate.source_trajectory, 'reason': 'exact family/scope/environment' if existing else 'new capability'}
        self.last_decisions.append(decision)
        return skill

    def _discard(self, candidate, reason):
        with self.store.db:
            self.store.event(candidate.name, candidate.version, 'discard', reason, candidate.source_trajectory[-1])
        self.last_decisions.append({'action': 'discard', 'name': candidate.name, 'reason': reason})
        return None

    def observe(self, trajectory):
        if trajectory['status'] != 'completed':
            return []
        candidates = [self.maintain(skill) for skill in extract_experience(trajectory)]
        # Persist a bounded delayed-feedback window, not an unbounded conversation.
        pending = {k: trajectory.get(k) for k in ('id', 'prompt', 'scope', 'environment', 'used_skill_versions')}
        pending['prompt'] = pending['prompt'][:1000]
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO evolution_pending VALUES (?,?)',
                                  (trajectory.get('scope', ''), json.dumps(pending, ensure_ascii=False)))
        return [skill for skill in candidates if skill]

    def consume_feedback(self, scope, prompt, current_id):
        self.last_decisions = []
        row = self.store.db.execute('SELECT payload FROM evolution_pending WHERE scope=?', (scope,)).fetchone()
        if not row:
            return None
        pending = json.loads(row[0])
        with self.store.db:
            self.store.db.execute('DELETE FROM evolution_pending WHERE scope=?', (scope,))
        if not CORRECTION.match(prompt):
            return None
        return self.maintain(_correction(prompt, [pending['id'], current_id], scope, pending.get('environment')))

    def validate(self, name, trajectory, *, useful, saved_calls=0):
        """External experiments/reviewers provide usefulness; no effectiveness judge here."""
        if trajectory['status'] != 'completed' and useful:
            raise ValueError('Incomplete trajectories cannot validate a skill')
        if 'used_skills' in trajectory and name not in trajectory['used_skills']:
            raise ValueError('Skill was not injected in this trajectory')
        versions = trajectory.get('used_skill_versions', {})
        version = versions.get(name)
        if versions and version is None:
            raise ValueError('No version-specific trial evidence for this skill')
        skill = self.store.get(name, version)
        if skill and version is None and skill.version > 1:
            raise ValueError('Version-specific trial evidence is required after a revision')
        if skill and trajectory['id'] in skill.source_trajectory:
            raise ValueError('Validate on a held-out trajectory, not the extraction source')
        return self.store.record(name, version=version, success=useful,
                                 evidence_id=trajectory['id'], saved_calls=saved_calls)

    def snapshot(self):
        return {'decisions': list(self.last_decisions),
                'pending_scopes': self.store.db.execute('SELECT count(*) FROM evolution_pending').fetchone()[0],
                'policy': {'activation_support': 2, 'maturity_support': 5,
                           'feedback_source': 'external', 'auto_effectiveness_evaluation': False}}
