"""Operator-private enrollment of one dedicated non-admin HA approver token.

Run interactively as the house-manager runtime user. This helper never creates
users, borrows other credentials, changes HA authentication storage or prints a
token. Create the dedicated non-admin account through HA's ordinary admin UI.
The resulting receipt contains only user IDs and a timestamp; installing its ID
in HA is a separate, reviewed operation. No approval or device request is made.
"""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone

WS_URL = 'ws://home-assistant.home-assistant.svc.cluster.local:8123/api/websocket'
KEY = 'HOUSE_MANAGER_APPROVAL_TOKEN'
USER_ID = re.compile(r'[0-9a-f]{32}')
TOKEN = re.compile(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
PROFILE_HOME = Path('/opt/data/profiles/house-manager')


def validate_identity(user, bot_user_id):
    if (not isinstance(user, dict) or not isinstance(user.get('id'), str)
            or not USER_ID.fullmatch(user['id']) or user['id'] == bot_user_id
            or user.get('is_admin') is not False or user.get('is_owner') is not False):
        raise ValueError('Dedicated active non-admin identity required')
    return user['id']


async def authenticate(token):
    import aiohttp
    async def no_redirect(*args):
        raise ValueError('Redirect refused')
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(no_redirect)
    timeout = aiohttp.ClientTimeout(total=25, connect=10)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout, trace_configs=[trace]) as session:
        async with session.ws_connect(WS_URL, max_msg_size=131072, heartbeat=None) as ws:
            async with asyncio.timeout(25):
                if (await ws.receive_json()).get('type') != 'auth_required':
                    raise ValueError('Authentication unavailable')
                await ws.send_json({'type':'auth', 'access_token':token})
                if (await ws.receive_json()).get('type') != 'auth_ok':
                    raise ValueError('Authentication denied')
                await ws.send_json({'id':1, 'type':'auth/current_user'})
                result = await ws.receive_json()
                if result.get('id') != 1 or result.get('type') != 'result' or result.get('success') is not True:
                    raise ValueError('Identity check unavailable')
                return result.get('result')


def _atomic_private(path, data):
    if path.is_symlink():
        raise ValueError('Symlink refused')
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def effective_secret_names(home):
    """Use normal configured providers in a private mapping; return NAMES only.

    Unlike the ordinary fail-open hydration snapshot, provisioning must refuse a
    failed configured provider: a missing source could hide an existing key.
    Never mutate os.environ, replace source configuration or print provider data.
    """
    from hermes_cli.config_backend import read_config_doc_readonly
    from agent.secret_scope import _is_global_env, load_env_file
    from agent.secret_sources.registry import apply_all
    from hermes_cli.managed_scope import load_managed_env
    config=read_config_doc_readonly(home/'config.yaml')
    if not isinstance(config,dict):
        raise ValueError('Profile configuration unavailable')
    sources=config.get('secrets') or {}
    if not isinstance(sources,dict):
        raise ValueError('Invalid secret source configuration')
    private_env={key:value for key,value in os.environ.items() if _is_global_env(key)}
    private_env.update(load_env_file(home/'.env'))
    private_env['HERMES_HOME']=str(home)
    report=apply_all(sources,home,environ=private_env)
    if any(source.result.ok is not True for source in report.sources):
        raise ValueError('Configured secret provider unavailable')
    names=set(private_env)|set(report.provenance)|set(load_managed_env())
    for source in report.sources:
        names.update(source.result.secrets)
    return frozenset(names)


def persist(home, token, user_id, bot_user_id, *, effective_names):
    """Preserve unrelated environment bytes. No default overwrite or rotation."""
    env = home / '.env'
    receipt = home / '.chat-approval-enrollment.json'
    if not isinstance(effective_names,frozenset) or KEY in effective_names:
        raise ValueError('Existing effective approval credential refused')
    if env.is_symlink() or receipt.exists() or receipt.is_symlink():
        raise ValueError('Existing enrollment or symlink refused')
    original = env.read_bytes() if env.exists() else b''
    if re.search(rb'(?m)^\s*(?:export\s+)?'+KEY.encode()+rb'\s*=', original):
        raise ValueError('Existing approval credential refused')
    if not isinstance(token,str) or len(token) > 8192 or not TOKEN.fullmatch(token):
        raise ValueError('Invalid token format')
    if not USER_ID.fullmatch(user_id) or not USER_ID.fullmatch(bot_user_id) or user_id == bot_user_id:
        raise ValueError('Invalid identities')
    suffix = (b'\n' if original and not original.endswith(b'\n') else b'') + KEY.encode()+b'='+token.encode('ascii')+b'\n'
    _atomic_private(env, original+suffix)
    record = {'version':1, 'approver_user_id':user_id, 'bot_user_id':bot_user_id,
              'authenticated_at':datetime.now(timezone.utc).isoformat(), 'token_printed':False}
    _atomic_private(receipt, (json.dumps(record,sort_keys=True)+'\n').encode())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bot-user-id', required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError('Interactive private terminal required')
    if os.getuid() != 10000 or Path(os.environ.get('HERMES_HOME','')).resolve() != PROFILE_HOME:
        raise ValueError('Run as house-manager runtime user under its own home')
    if not USER_ID.fullmatch(args.bot_user_id):
        raise ValueError('Invalid bot identity')
    if (PROFILE_HOME/'.chat-approval-enrollment.json').exists() or KEY in effective_secret_names(PROFILE_HOME):
        raise ValueError('Existing enrollment or external approval key refused')
    token = getpass.getpass('Dedicated non-admin HA approver token (hidden): ')
    if len(token) > 8192 or not TOKEN.fullmatch(token):
        raise ValueError('Invalid token format')
    user_id = validate_identity(asyncio.run(authenticate(token)), args.bot_user_id)
    record = persist(PROFILE_HOME,token,user_id,args.bot_user_id,
                     effective_names=effective_secret_names(PROFILE_HOME))
    print(json.dumps(record,sort_keys=True))
    print('Enrollment stored privately. No automation was approved or changed.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Enrollment failed or incomplete. No token is printed. Check private enrollment state before retrying.', file=sys.stderr)
        raise SystemExit(1)
