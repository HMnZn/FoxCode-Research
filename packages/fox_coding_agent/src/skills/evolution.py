"""Extract conservative candidates from failure -> recovery tool trajectories."""
import hashlib
import json
import re
from .store import Skill


def extract_experience(trajectory):
    failures = {}
    repeated = {}
    candidates = []
    for step in trajectory["tools"]:
        call, result = step["call"], step["result"]
        key = (call["name"], call["arguments"].get("file_path", ""))
        if result["is_error"]:
            failures[key] = step
            fingerprint = (key, result["content"][:200])
            repeated[fingerprint] = repeated.get(fingerprint, 0) + 1
            if repeated[fingerprint] == 2:
                trigger = f"Repeated {call['name']} failure in {key[1] or 'shell environment'}"
                name = "repeated-" + hashlib.sha256(str(fingerprint).encode()).hexdigest()[:12]
                candidates.append(Skill(name, trigger, trigger,
                    f"Before repeating the same call, inspect its cause: {result['content'][:500]}. "
                    "Verify the current environment/file state, then test a different strategy.",
                    tags=[call["name"]], source_trajectory=[trajectory["id"]]))
            continue
        failed = failures.pop(key, None)
        if not failed:
            continue
        old, new = failed["call"]["arguments"], call["arguments"]
        if old == new:
            continue
        target = new.get("file_path", "shell environment")
        # Keep the concrete recovery evidence; this is a candidate, not a rule yet.
        trigger = f"{call['name']} failure in {target}"
        description = f"Recover {call['name']} after {failed['result']['content'][:160]}"
        name = "recover-" + hashlib.sha256((trigger + json.dumps(old, sort_keys=True)).encode()).hexdigest()[:12]
        instructions = (f"Before retrying {call['name']}, verify the current file/environment.\n"
                        f"Failed arguments: {old}\nSuccessful alternative: {new}\n"
                        "Use this historical strategy only when the same cause is verified.")
        candidates.append(Skill(name, description, trigger, instructions,
                                tags=[call["name"], str(target)], source_trajectory=[trajectory["id"]]))
    correction = trajectory.get("prompt", "")
    if re.match(r"\s*(?:纠正[：:]|不对[，,:：]|你错了|correction:|actually[, :])", correction, re.I):
        name = "correction-" + hashlib.sha256(correction.encode()).hexdigest()[:12]
        candidates.append(Skill(name, correction[:160], "User-corrected coding behavior",
                                correction, tags=["user-correction"], source_trajectory=[trajectory["id"]]))
    return candidates


class SkillEvolution:
    def __init__(self, store):
        self.store = store

    def observe(self, trajectory):
        if trajectory["status"] != "completed":
            return []
        return [self.store.propose(skill) for skill in extract_experience(trajectory)]

    def validate(self, name, trajectory, *, useful, saved_calls=0):
        """An experiment/reviewer supplies usefulness; model completion isn't proof."""
        if trajectory["status"] != "completed" and useful:
            raise ValueError("Incomplete trajectories cannot validate a skill")
        skill = self.store.get(name)
        if skill and trajectory["id"] in skill.source_trajectory:
            raise ValueError("Validate on a held-out trajectory, not the extraction source")
        return self.store.record(name, success=useful, evidence_id=trajectory["id"], saved_calls=saved_calls)
