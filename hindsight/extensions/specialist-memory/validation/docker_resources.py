"""Test-harness-only resources; no Docker execution until a runner is injected.

Runner takes Docker argv WITHOUT prefix and returns a text CompletedProcess.
Parent supplies prefix, capture_output=True, check=False and a bounded timeout.
Handles/events never retain command output. Unknown ownership fails closed.
"""
from dataclasses import dataclass
import json
import re
import uuid
import ipaddress
from pathlib import Path

LABEL = 'homelab.specialist-validation.run'
MODEL_ROOT = Path(__file__).resolve().parents[4] / 'verification/cache/specialist-models'


@dataclass(frozen=True)
class Event:
    stage: str
    exit_code: int | None


@dataclass(frozen=True)
class Handle:
    kind: str
    name: str
    owner: str
    image: str | None = None
    id: str | None = None
    failed: bool = False
    removed: bool = False


def _mark(h, **changes):
    for key, value in changes.items():
        object.__setattr__(h, key, value)


class DockerResources:
    def __init__(self, runner):
        self.runner = runner
        self.handles = []
        self.events = []
        self.owner = uuid.uuid4().hex

    def _run(self, stage, args):
        try:
            result = self.runner(args)
            code, out, err = result.returncode, result.stdout, result.stderr
        except Exception:
            code, out, err = None, '', ''
        code = code if type(code) is int and -255 <= code <= 255 else None
        self.events.append(Event(stage, code))
        return code, out if isinstance(out, str) else '', err if isinstance(err, str) else ''

    def create(self, kind, *, image=None, command=(), network=None, volume=None,
               ports=(), environment=None, models=None, subnet=None):
        if kind not in ('container', 'network', 'volume') or (kind == 'container' and
                (not isinstance(image, str) or not image or image.startswith('-') or any(c.isspace() for c in image))):
            raise ValueError('invalid resource specification')
        options = ['--log-driver','none']
        selected = None
        if subnet is not None:
            selected = ipaddress.ip_network(subnet,strict=True)
            if kind != 'network' or selected.version != 4 or not selected.is_private or selected.prefixlen != 28:
                raise ValueError('only an isolated private /28 network is admitted')
        for resource, expected in ((network, 'network'), (volume, 'volume')):
            if resource is not None and (not self._usable(resource) or resource.kind != expected):
                raise ValueError('resource must belong to this lifecycle')
        if kind != 'container' and (network or volume or ports or environment or command or image or models):
            raise ValueError('container options require container')
        if models is not None:
            path = Path(models).resolve(strict=True)
            if not path.is_dir() or not path.is_relative_to(MODEL_ROOT.resolve()) or volume:
                raise ValueError('only public model cache data can be mounted')
            options += ['--mount',f'type=bind,src={path},dst=/models,readonly',
                        '--read-only','--user','1000:1000','--workdir','/tmp',
                        '--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777',
                        '--cap-drop','ALL','--security-opt','no-new-privileges',
                        '--pids-limit','256','--memory','4g','--cpus','2']
        options += ['--network', network.id if network else 'none']
        if volume:
            options += ['--mount', f'type=volume,src={volume.id},dst=/var/lib/postgresql/data']
        for host, target in ports:
            if any(type(port) is not int or not 1 <= port <= 65535 for port in (host, target)):
                raise ValueError('invalid loopback port')
            options += ['--publish', f'127.0.0.1:{host}:{target}']
        for key, value in (environment or {}).items():
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key) or not isinstance(value, str) or '\x00' in value:
                raise ValueError('invalid environment entry')
            options += ['--env', f'{key}={value}']
        h = Handle(kind, 'specialist-validation-' + uuid.uuid4().hex, self.owner, image)
        self.handles.append(h)  # Record attempt BEFORE dispatch (including exceptions).
        args = [kind, 'create', '--label', f'{LABEL}={h.owner}']
        if kind == 'container':
            args += ['--name', h.name, '--pull=never', *options, image, *command]
        else:
            args += (['--internal',*(['--subnet',str(selected)] if subnet else [])] if kind == 'network' else []) + [h.name]
        code, out, _ = self._run('create', args)
        identity = out.strip()
        if code == 0 and self._valid_id(h, identity):
            _mark(h, id=identity)
        else:
            # Exactly one exact-name inspection; never list/filter other resources.
            state = self._inspect(h, bind=True)
            _mark(h, removed=state == 'absent', failed=state is None)
        return h

    @staticmethod
    def _valid_id(h, identity):
        return identity == h.name if h.kind == 'volume' else bool(re.fullmatch('[0-9a-f]{64}', identity))

    def _inspect(self, h, *, bind=False):
        target = h.id or h.name
        code, out, err = self._run('inspect', [h.kind, 'inspect', target])
        missing = (f'No such {h.kind}: {target}', f'network {target} not found' if h.kind == 'network'
                   else f'get {target}: no such volume' if h.kind == 'volume' else f'No such container: {target}')
        if code == 1 and out.strip() in ('', '[]') and any(err.strip() == prefix + text
                for prefix in ('', 'Error: ', 'Error response from daemon: ') for text in missing):
            return 'absent'
        if code != 0:
            return None
        try:
            records = json.loads(out)
            if not isinstance(records, list) or len(records) != 1:
                return None
            data = records[0]
            identity = data['Name'] if h.kind == 'volume' else data['Id']
            if not isinstance(identity, str) or not self._valid_id(h, identity) or (h.id and identity != h.id):
                return None
            if data['Name'] != ('/' + h.name if h.kind == 'container' else h.name):
                return None
            config = data['Config'] if h.kind == 'container' else data
            if config['Labels'][LABEL] != h.owner:
                return None
            status = 'stopped'
            if h.kind == 'container':
                if config['Image'] != h.image:
                    return None
                status = data['State']['Status']
                if status not in ('created', 'exited', 'dead', 'running', 'restarting', 'paused'):
                    return None
            if h.kind == 'network' and data['Internal'] is not True:
                return None
            if bind:
                _mark(h, id=identity)
            return status
        except (ValueError, KeyError, TypeError):
            return None

    def _usable(self, h):
        return any(item is h for item in self.handles) and not h.failed and not h.removed and bool(h.id)

    def start(self, h):
        if not self._usable(h) or h.kind != 'container' or self._inspect(h) not in ('created', 'exited'):
            return False
        code, _, _ = self._run('start', ['container', 'start', h.id])
        return code == 0 and self._inspect(h) == 'running'

    def stop(self, h):
        if not self._usable(h):
            return False
        status = self._inspect(h)
        if status in ('created', 'exited', 'dead', 'stopped', 'absent'):
            return True
        if status not in ('running', 'restarting'):
            return False
        code, _, _ = self._run('stop', ['container', 'stop', '--time', '10', h.id])
        return code == 0 and self._inspect(h) in ('exited', 'dead', 'created', 'absent')

    def remove(self, h):
        if not any(item is h for item in self.handles) or h.failed:
            return False
        if h.removed:
            return True
        status = self._inspect(h, bind=not h.id)
        if status == 'absent':
            _mark(h, removed=True)
            return True
        if status in ('running', 'restarting'):
            code, _, _ = self._run('stop', ['container', 'stop', '--time', '10', h.id])
            if code != 0:
                _mark(h, failed=True)
                return False
            status = self._inspect(h)
            if status == 'absent':
                _mark(h, removed=True)
                return True
        if status not in ('created', 'exited', 'dead', 'stopped'):
            _mark(h, failed=True)
            return False
        code, _, _ = self._run('remove', [h.kind, 'rm', h.id])
        removed = code == 0 and self._inspect(h) == 'absent'
        _mark(h, removed=removed, failed=not removed)
        return removed

    def cleanup(self):
        results = [self.remove(h) for h in reversed(self.handles)]
        return all(results)
