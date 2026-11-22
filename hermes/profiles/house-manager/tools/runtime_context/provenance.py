"""Provenance predicate for later adapter integration, NOT an authorization gate.

Pass only the runtime's active_policy(), never model/client arguments or a fabricated
object. Existing profile, actor, approval-principal and choice checks remain required.
"""
import json

_ALLOWED = {'cli': 'cli', 'tui': 'tui', 'gui': 'desktop'}


def trusted_launch_source(policy) -> str | None:
    """Return cli/tui/gui only for a coherent owner-frozen interactive launch.

    platform alone is insufficient: tool and oneshot both present as cli.
    gui is the creation label, desktop is its presentation surface, not an alias
    accepted by this gate. Missing, malformed, or contradictory evidence denies.
    """
    if policy is None:
        return None
    source = getattr(policy, 'source', None)
    if not isinstance(source, str) or source not in _ALLOWED:
        return None
    if getattr(policy, 'platform', None) != _ALLOWED[source]:
        return None
    try:
        request = json.loads(policy.request_json)
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(request, dict) or request.get('source') != source:
        return None
    return source
