"""Generate Patroni + MySQL configs for single- or multi-node layouts.

Templates live under ``<repo>/templates/mysql/`` (xenon / xenon-mgr aligned).
Default output is ``<repo>/deploy/mysql-ha/``.

Usage::

    patroni_mysql_init --force
    patroni_mysql_init -o deploy/mysql-ha-mgr --mode mgr --nodes 3 --force
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from .config import ConfigHandler
from .versioning import (
    build_mysqld_parameters,
    resolve_mysql_version,
    version_summary,
)

# Xenon-compatible "infinite" semi-sync timeout (ms): never degrade to async.
SEMI_SYNC_TIMEOUT_INFINITE_MS = 10**18
SEMI_SYNC_TIMEOUT_TWO_NODE_MS = 10000

# Memory defaults (industry-oriented; budget shared across local MySQL nodes).
DEFAULT_MEMORY_PCT = 50
MIN_BUFFER_POOL_BYTES = 128 * 1024 * 1024
BUFFER_POOL_ALIGN = 128 * 1024 * 1024


def find_repo_root(start: Optional[str] = None) -> str:
    """Locate metatroni repo root (directory containing ``templates/mysql``)."""
    env = os.environ.get('METATRONI_ROOT')
    if env and os.path.isdir(os.path.join(env, 'templates', 'mysql')):
        return os.path.abspath(env)

    cur = os.path.abspath(start or os.getcwd())
    for _ in range(12):
        if os.path.isdir(os.path.join(cur, 'templates', 'mysql')):
            return cur
        if os.path.isfile(os.path.join(cur, 'setup.py')) and os.path.isdir(
                os.path.join(cur, 'patroni')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    here = os.path.abspath(os.path.dirname(__file__))
    candidate = os.path.abspath(os.path.join(here, '..', '..', 'templates', 'mysql'))
    if os.path.isdir(candidate):
        return os.path.abspath(os.path.join(here, '..', '..'))
    return os.getcwd()


def templates_dir(repo_root: Optional[str] = None) -> str:
    root = repo_root or find_repo_root()
    path = os.path.join(root, 'templates', 'mysql')
    if not os.path.isdir(path):
        raise FileNotFoundError(
            f'MySQL templates not found at {path}; expected repo templates/mysql/')
    return path


def default_output_dir(repo_root: Optional[str] = None) -> str:
    return os.path.join(repo_root or find_repo_root(), 'deploy', 'mysql-ha')


def _load_yaml_dict(path: str) -> Dict[str, str]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{path} must be a mapping')
    out: Dict[str, str] = {}
    for k, v in data.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out


def load_template_parameters(name: str, repo_root: Optional[str] = None) -> Dict[str, str]:
    """Load ``templates/mysql/<name>.yaml`` as string-valued parameters."""
    path = os.path.join(templates_dir(repo_root), f'{name}.yaml')
    return _load_yaml_dict(path)


def detect_total_memory_bytes() -> int:
    """Return host RAM in bytes (Linux ``/proc/meminfo``, else 8 GiB fallback)."""
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 8 * 1024 * 1024 * 1024


def parse_size(value: str) -> int:
    """Parse ``512M``, ``2G``, ``1073741824``, or bare integers (bytes)."""
    raw = value.strip().replace('_', '').replace(' ', '')
    if not raw:
        raise ValueError('empty size')
    lower = raw.lower()
    units: Tuple[Tuple[str, int], ...] = (
        ('tib', 1024 ** 4), ('tb', 1024 ** 4), ('t', 1024 ** 4),
        ('gib', 1024 ** 3), ('gb', 1024 ** 3), ('g', 1024 ** 3),
        ('mib', 1024 ** 2), ('mb', 1024 ** 2), ('m', 1024 ** 2),
        ('kib', 1024), ('kb', 1024), ('k', 1024),
    )
    for suffix, mul in units:
        if lower.endswith(suffix):
            return int(float(lower[:-len(suffix)]) * mul)
    return int(raw)


def format_size_mysql(num_bytes: int) -> str:
    """Format bytes as MySQL-friendly size (``128M``, ``2G``)."""
    if num_bytes >= 1024 ** 3 and num_bytes % (1024 ** 3) == 0:
        return f'{num_bytes // (1024 ** 3)}G'
    if num_bytes >= 1024 ** 2 and num_bytes % (1024 ** 2) == 0:
        return f'{num_bytes // (1024 ** 2)}M'
    if num_bytes >= 1024 and num_bytes % 1024 == 0:
        return f'{num_bytes // 1024}K'
    return str(num_bytes)


def align_down(value: int, alignment: int) -> int:
    if value < alignment:
        return alignment
    return value - (value % alignment)


def compute_buffer_pool_bytes(
        total_memory: int,
        memory_pct: float,
        nodes: int,
        explicit: Optional[int] = None) -> int:
    """Per-node InnoDB buffer pool size."""
    if explicit is not None:
        return max(MIN_BUFFER_POOL_BYTES, explicit)
    if nodes < 1:
        raise ValueError('nodes must be >= 1')
    budget = int(total_memory * (memory_pct / 100.0))
    per_node = budget // nodes
    return max(MIN_BUFFER_POOL_BYTES, align_down(per_node, BUFFER_POOL_ALIGN))


def memory_derived_params(buffer_pool: int,
                          repo_root: Optional[str] = None) -> Dict[str, str]:
    """Deprecated helper — use versioning.apply_memory_params via build_mysqld_parameters."""
    from .versioning import apply_memory_params, parse_mysql_version
    return apply_memory_params(
        parse_mysql_version('8.0.35'), buffer_pool, format_size_mysql, align_down)


def base_mysql_parameters(repo_root: Optional[str] = None) -> Dict[str, str]:
    from .versioning import build_base_parameters, parse_mysql_version
    return build_base_parameters(parse_mysql_version('8.0.35'))


def semi_sync_parameters(nodes: int,
                        repo_root: Optional[str] = None) -> Dict[str, str]:
    from .versioning import apply_semi_sync_params, parse_mysql_version
    return apply_semi_sync_params(
        parse_mysql_version('8.0.35'), nodes,
        SEMI_SYNC_TIMEOUT_INFINITE_MS if nodes >= 3 else SEMI_SYNC_TIMEOUT_TWO_NODE_MS,
        max(1, (nodes - 1) // 2))


def mgr_parameters(group_name: str, local_host: str, mysql_port: int,
                  seeds: str, nodes: int,
                  repo_root: Optional[str] = None) -> Dict[str, str]:
    from .versioning import apply_mgr_params, parse_mysql_version
    return apply_mgr_params(
        parse_mysql_version('8.0.35'), group_name, local_host, mysql_port, seeds, nodes)


def build_node_spec(
        index: int,
        *,
        name_prefix: str,
        host: str,
        mysql_port_base: int,
        api_port_base: int,
        output_dir: str) -> Dict[str, Any]:
    name = f'{name_prefix}{index}'
    mysql_port = mysql_port_base + index
    api_port = api_port_base + index
    node_dir = os.path.join(output_dir, name)
    data_dir = os.path.join(node_dir, 'data')
    return {
        'index': index,
        'name': name,
        'host': host,
        'mysql_port': mysql_port,
        'api_port': api_port,
        'mgr_port': mysql_port + 10,
        'node_dir': node_dir,
        'data_dir': data_dir,
        'config_dir': node_dir,
        'patroni_yml': os.path.join(node_dir, 'patroni.yml'),
        'my_cnf': os.path.join(node_dir, 'my.cnf'),
        'server_id': index + 1,
    }


def build_patroni_config(
        node: Dict[str, Any],
        *,
        scope: str,
        namespace: str,
        bin_dir: str,
        etcd_hosts: str,
        use_etcd3: bool,
        mode: str,
        parameters: Dict[str, str],
        superuser_password: str,
        replication_password: str,
        create_replica_methods: List[str],
        nodes: int) -> Dict[str, Any]:
    host = node['host']
    mysql_listen = f"{host}:{node['mysql_port']}"
    api_listen = f"{host}:{node['api_port']}"
    cfg: Dict[str, Any] = {
        'scope': scope,
        'namespace': namespace,
        'name': node['name'],
        'database': {'type': 'mysql'},
        'restapi': {
            'listen': api_listen,
            'connect_address': api_listen,
        },
        'bootstrap': {
            'dcs': {
                'ttl': 30,
                'loop_wait': 10,
                'retry_timeout': 10,
                'maximum_lag_on_failover': 1048576,
            },
        },
        'mysql': {
            'name': node['name'],
            'scope': scope,
            'listen': mysql_listen,
            'connect_address': mysql_listen,
            'data_dir': node['data_dir'],
            'config_dir': node['config_dir'],
            'bin_dir': bin_dir,
            'port': node['mysql_port'],
            'server_id': node['server_id'],
            'create_replica_methods': create_replica_methods,
            'authentication': {
                'superuser': {
                    'username': 'root',
                    'password': superuser_password,
                },
                'replication': {
                    'username': 'replicator',
                    'password': replication_password,
                },
            },
            'parameters': dict(parameters),
        },
        'tags': {
            'noloadbalance': False,
            'clonefrom': False,
            'nostream': False,
        },
    }
    dcs_key = 'etcd3' if use_etcd3 else 'etcd'
    cfg[dcs_key] = {'hosts': etcd_hosts}
    if mode in ('semi-sync', 'mgr'):
        cfg['mysql']['parameters'].setdefault('cluster_size', str(nodes))
    return cfg


def render_haproxy_cfg(nodes: Sequence[Dict[str, Any]],
                       primary_bind: str = '*:5000',
                       replica_bind: str = '*:5001',
                       stats_bind: str = '*:7000') -> str:
    """HAProxy TCP frontends that route via Patroni REST health checks.

    Port 5000 → current primary (``HEAD /primary``).
    Port 5001 → healthy replicas (``HEAD /replica``).
    """
    lines = [
        'global',
        '    maxconn 100',
        '',
        'defaults',
        '    log global',
        '    mode tcp',
        '    retries 2',
        '    timeout client 30m',
        '    timeout connect 4s',
        '    timeout server 30m',
        '    timeout check 5s',
        '',
        'listen stats',
        '    mode http',
        f'    bind {stats_bind}',
        '    stats enable',
        '    stats uri /',
        '',
        'listen mysql_primary',
        f'    bind {primary_bind}',
        '    option httpchk HEAD /primary',
        '    http-check expect status 200',
        '    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions',
    ]
    for n in nodes:
        lines.append(
            f'    server {n["name"]} {n["host"]}:{n["mysql_port"]} '
            f'maxconn 100 check port {n["api_port"]}'
        )
    lines.extend([
        '',
        'listen mysql_replicas',
        f'    bind {replica_bind}',
        '    balance roundrobin',
        '    option httpchk HEAD /replica',
        '    http-check expect status 200',
        '    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions',
    ])
    for n in nodes:
        lines.append(
            f'    server {n["name"]} {n["host"]}:{n["mysql_port"]} '
            f'maxconn 100 check port {n["api_port"]}'
        )
    lines.append('')
    return '\n'.join(lines)


def render_helpers(output_dir: str, nodes: Sequence[Dict[str, Any]],
                   pythonpath_hint: str = '') -> None:
    start_lines = [
        '#!/usr/bin/env bash',
        'set -euo pipefail',
        'ROOT="$(cd "$(dirname "$0")" && pwd)"',
        'export PATH="${PATH}"',
    ]
    if pythonpath_hint:
        start_lines.append(f'export PYTHONPATH="{pythonpath_hint}:${{PYTHONPATH:-}}"')
    start_lines.append('mkdir -p "$ROOT/logs"')
    for n in nodes:
        start_lines.append(
            f'nohup patroni "$ROOT/{n["name"]}/patroni.yml" '
            f'>>"$ROOT/logs/{n["name"]}.log" 2>&1 &'
        )
        start_lines.append(f'echo $! > "$ROOT/logs/{n["name"]}.pid"')
        start_lines.append('disown $! 2>/dev/null || true')
        start_lines.append(f'echo "started {n["name"]} pid=$(cat "$ROOT/logs/{n["name"]}.pid")"')
    start_lines.append(
        'echo "Use: patronictl -c $ROOT/{0}/patroni.yml list"'.format(nodes[0]['name']))

    stop_lines = [
        '#!/usr/bin/env bash',
        'set -euo pipefail',
        'ROOT="$(cd "$(dirname "$0")" && pwd)"',
        'for f in "$ROOT"/logs/*.pid; do',
        '  [[ -f "$f" ]] || continue',
        '  pid=$(cat "$f" || true)',
        '  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then',
        '    kill "$pid" || true',
        '    echo "stopped pid=$pid ($f)"',
        '  fi',
        '  rm -f "$f"',
        'done',
    ]

    port_lines = '\n'.join(
        f"- {n['name']}: mysql={n['mysql_port']} api={n['api_port']} mgr={n['mgr_port']}"
        for n in nodes
    )
    first = nodes[0]['name']
    readme = (
        f'# Generated MySQL HA layout ({len(nodes)} node(s))\n\n'
        f'Templates: ``templates/mysql/`` (xenon / xenon-mgr aligned).\n\n'
        f'## Layout\n```\n{output_dir}/\n'
        f'  start.sh / stop.sh\n  haproxy.cfg\n  logs/\n'
        f'  <node>/patroni.yml\n  <node>/my.cnf\n  <node>/data/\n```\n\n'
        f'## Ports\n{port_lines}\n\n'
        f'## Start\n```bash\n# ensure etcd is running, then:\n'
        f'./start.sh\npatronictl -c ./{first}/patroni.yml list\n```\n\n'
        f'## HAProxy (optional)\n'
        f'Generated ``haproxy.cfg`` routes:\n'
        f'- ``*:5000`` → current primary (``HEAD /primary``)\n'
        f'- ``*:5001`` → healthy replicas (``HEAD /replica``)\n'
        f'- ``*:7000`` → HAProxy stats\n\n'
        f'```bash\nhaproxy -f ./haproxy.cfg -db\n'
        f'mysql -h 127.0.0.1 -P 5000 -u root\n```\n'
    )

    with open(os.path.join(output_dir, 'start.sh'), 'w') as f:
        f.write('\n'.join(start_lines) + '\n')
    with open(os.path.join(output_dir, 'stop.sh'), 'w') as f:
        f.write('\n'.join(stop_lines) + '\n')
    with open(os.path.join(output_dir, 'haproxy.cfg'), 'w') as f:
        f.write(render_haproxy_cfg(nodes))
    with open(os.path.join(output_dir, 'README.md'), 'w') as f:
        f.write(readme)
    os.chmod(os.path.join(output_dir, 'start.sh'), 0o755)
    os.chmod(os.path.join(output_dir, 'stop.sh'), 0o755)


def generate_cluster(args: argparse.Namespace) -> List[Dict[str, Any]]:
    nodes_count = args.nodes
    if nodes_count < 1:
        raise SystemExit('--nodes must be >= 1')
    if args.mode == 'mgr' and nodes_count < 3:
        raise SystemExit('MGR mode requires --nodes >= 3')

    repo_root = find_repo_root()
    output_dir = os.path.abspath(args.output_dir)
    if os.path.exists(output_dir) and os.listdir(output_dir) and not args.force:
        raise SystemExit(f'{output_dir} is not empty; pass --force to overwrite')

    os.makedirs(output_dir, exist_ok=True)

    try:
        mysql_ver = resolve_mysql_version(
            explicit=getattr(args, 'mysql_version', None),
            bin_dir=args.bin_dir or '')
    except Exception as e:
        raise SystemExit(f'Cannot resolve MySQL version: {e}') from e

    if args.mode == 'mgr' and not mysql_ver.has_mgr:
        raise SystemExit(f'MGR mode requires MySQL 5.7.17+/8.0+ (got {mysql_ver})')

    total_memory = (parse_size(args.total_memory) if args.total_memory
                    else detect_total_memory_bytes())
    explicit_bp = (parse_size(args.innodb_buffer_pool_size)
                   if args.innodb_buffer_pool_size else None)
    buffer_pool = compute_buffer_pool_bytes(
        total_memory, args.memory_pct, nodes_count, explicit_bp)

    nodes = [
        build_node_spec(
            i,
            name_prefix=args.name_prefix,
            host=args.host,
            mysql_port_base=args.mysql_port_base,
            api_port_base=args.api_port_base,
            output_dir=output_dir,
        )
        for i in range(nodes_count)
    ]

    group_name = args.mgr_group_name or str(uuid.uuid4())
    seeds = ','.join(f"{n['host']}:{n['mgr_port']}" for n in nodes)

    create_methods = [m.strip() for m in args.create_replica_methods.split(',') if m.strip()]
    if not create_methods:
        create_methods = ['mysqldump']

    for node in nodes:
        os.makedirs(node['data_dir'], exist_ok=True)

        params = build_mysqld_parameters(
            mysql_ver,
            mode=args.mode,
            nodes=nodes_count,
            buffer_pool=buffer_pool,
            format_size=format_size_mysql,
            align_down=align_down,
            timeout_infinite_ms=SEMI_SYNC_TIMEOUT_INFINITE_MS,
            timeout_two_node_ms=SEMI_SYNC_TIMEOUT_TWO_NODE_MS,
            group_name=group_name,
            local_host=node['host'],
            mysql_port=node['mysql_port'],
            seeds=seeds,
        )
        params['server_id'] = str(node['server_id'])
        params['relay_log'] = os.path.join(node['data_dir'], 'mysql-relay-bin')
        params['relay_log_index'] = os.path.join(node['data_dir'], 'mysql-relay-bin.index')
        params['tmpdir'] = node['data_dir']
        params['slow_query_log_file'] = os.path.join(node['data_dir'], 'mysql-slow.log')
        if args.mode == 'mgr':
            params['report_host'] = node['host']
            params['report_port'] = str(node['mysql_port'])

        for item in args.set or []:
            if '=' not in item:
                raise SystemExit(f'invalid --set {item!r}; expected key=value')
            k, v = item.split('=', 1)
            params[k.strip()] = v.strip()

        patroni_cfg = build_patroni_config(
            node,
            scope=args.scope,
            namespace=args.namespace,
            bin_dir=args.bin_dir,
            etcd_hosts=args.etcd,
            use_etcd3=args.etcd_version == 3,
            mode=args.mode,
            parameters=params,
            superuser_password=args.superuser_password,
            replication_password=args.replication_password,
            create_replica_methods=create_methods,
            nodes=nodes_count,
        )
        # Stash detected version for operators / future runtime use
        patroni_cfg['mysql']['version'] = str(mysql_ver)

        with open(node['patroni_yml'], 'w') as f:
            yaml.safe_dump(patroni_cfg, f, default_flow_style=False, sort_keys=False)

        handler = ConfigHandler(patroni_cfg['mysql'])
        handler.write_my_cnf()

    py_hint = args.pythonpath or repo_root
    render_helpers(output_dir, nodes, pythonpath_hint=py_hint)

    summary = {
        'output_dir': output_dir,
        'templates': templates_dir(repo_root),
        'mysql_version': version_summary(mysql_ver),
        'mode': args.mode,
        'nodes': nodes_count,
        'total_memory': format_size_mysql(total_memory),
        'memory_pct': args.memory_pct,
        'innodb_buffer_pool_size_per_node': format_size_mysql(buffer_pool),
        'etcd': args.etcd,
        'etcd_version': args.etcd_version,
        'aligned_with': [
            'xenon multi-version handlers (5.6/5.7/8.0)',
            'radondb-ansible my.cnf.Debian.j2',
            'templates/mysql/VERSIONS.md',
        ],
    }
    if args.mode == 'mgr':
        summary['mgr_group_name'] = group_name
    with open(os.path.join(output_dir, 'cluster-summary.yaml'), 'w') as f:
        yaml.safe_dump(summary, f, default_flow_style=False)

    # Attach for main() printing
    args._resolved_mysql_version = mysql_ver  # type: ignore[attr-defined]
    return nodes


def build_arg_parser() -> argparse.ArgumentParser:
    default_out = default_output_dir()
    p = argparse.ArgumentParser(
        prog='patroni_mysql_init',
        description='Initialize Patroni + MySQL configs from templates/mysql (xenon-aligned)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
        templates: <repo>/templates/mysql/
        default output: {default_out}

        examples:
          patroni_mysql_init --force --bin-dir /usr/local/mysql/bin
          patroni_mysql_init -o deploy/mysql-single --nodes 1 --mode async --memory-pct 70 --force
          patroni_mysql_init --innodb-buffer-pool-size 1G --force
          patroni_mysql_init -o deploy/mysql-mgr --mode mgr --force
        """),
    )
    p.add_argument('-o', '--output-dir', default=default_out,
                   help=f'Directory to write cluster layout (default: {default_out})')
    p.add_argument('--nodes', type=int, default=3, help='Number of MySQL/Patroni nodes (default: 3)')
    p.add_argument('--mode', choices=('async', 'semi-sync', 'mgr'), default='semi-sync',
                   help='Replication template (default: semi-sync)')
    p.add_argument('--scope', default='mysql-cluster', help='Patroni cluster scope/name')
    p.add_argument('--namespace', default='/service/', help='DCS namespace')
    p.add_argument('--name-prefix', default='mysql', help='Node name prefix (mysql0, mysql1, ...)')
    p.add_argument('--host', default='127.0.0.1',
                   help='Bind/advertise host for all local instances (single-host multi-node)')
    p.add_argument('--mysql-port-base', type=int, default=3306, help='MySQL port for node 0')
    p.add_argument('--api-port-base', type=int, default=8008, help='REST API port for node 0')
    p.add_argument('--bin-dir', default='', help='MySQL bin directory (mysqld, mysql, ...)')
    p.add_argument('--mysql-version', default=None,
                   help='MySQL version or family: 5.6, 5.7, 8.0, 8.4, 8.x, 9.0, 9.x '
                        '(default: detect via mysqld --version)')
    p.add_argument('--etcd', default='127.0.0.1:2379', help='etcd hosts (comma-separated)')
    p.add_argument('--etcd-version', type=int, choices=(2, 3), default=3,
                   help='Write etcd: (2) or etcd3: (3) section (default: 3)')
    p.add_argument('--memory-pct', type=float, default=DEFAULT_MEMORY_PCT,
                   help=f'Percent of total RAM shared by all local MySQL nodes '
                        f'(default: {DEFAULT_MEMORY_PCT})')
    p.add_argument('--total-memory', default=None,
                   help='Override detected RAM (e.g. 16G); useful in containers')
    p.add_argument('--innodb-buffer-pool-size', default=None,
                   help='Per-node buffer pool absolute size (e.g. 2G); overrides --memory-pct')
    p.add_argument('--superuser-password', default='', help='root password (default: empty)')
    p.add_argument('--replication-password', default='rep-pass', help='replicator password')
    p.add_argument('--create-replica-methods', default='mysqldump',
                   help='Comma list: mysqldump,xtrabackup,...')
    p.add_argument('--mgr-group-name', default=None, help='Fixed MGR UUID (default: random)')
    p.add_argument('--set', action='append', default=[],
                   help='Extra mysqld parameter key=value (repeatable)')
    p.add_argument('--pythonpath', default='',
                   help='Optional PYTHONPATH for start.sh (default: repo root)')
    p.add_argument('--force', action='store_true', help='Allow writing into a non-empty output dir')
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.memory_pct <= 0 or args.memory_pct > 90:
        parser.error('--memory-pct must be in (0, 90]')

    nodes = generate_cluster(args)
    total_memory = (parse_size(args.total_memory) if args.total_memory
                    else detect_total_memory_bytes())
    explicit_bp = (parse_size(args.innodb_buffer_pool_size)
                   if args.innodb_buffer_pool_size else None)
    bp = compute_buffer_pool_bytes(total_memory, args.memory_pct, args.nodes, explicit_bp)

    print(f'Wrote {len(nodes)} node(s) under {os.path.abspath(args.output_dir)}')
    print(f'  templates={templates_dir()}')
    ver = getattr(args, '_resolved_mysql_version', None)
    if ver is not None:
        print(f'  mysql_version={ver} family={ver.family} '
              f'source_replica_names={ver.uses_source_replica_names}')
    print(f'  mode={args.mode}  buffer_pool/node={format_size_mysql(bp)}  '
          f'(RAM {format_size_mysql(total_memory)} × {args.memory_pct}% / {args.nodes})')
    for n in nodes:
        print(f'  {n["name"]}: mysql=:{n["mysql_port"]} api=:{n["api_port"]} '
              f'mgr=:{n["mgr_port"]}  {n["patroni_yml"]}')
    print(f'  helpers: {os.path.join(os.path.abspath(args.output_dir), "start.sh")}')
    print(f'  haproxy: {os.path.join(os.path.abspath(args.output_dir), "haproxy.cfg")} '
          f'(primary :5000, replicas :5001, stats :7000)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
