#!/usr/bin/env bash
# Start the existing Hala database before running Bench. Never initialize a new database.
set -euo pipefail

HALA_BENCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
while [[ ! -x "$HALA_BENCH_DIR/env/bin/python" || ! -d "$HALA_BENCH_DIR/sites" ]]; do
    if [[ "$HALA_BENCH_DIR" == / ]]; then
        echo 'Could not find the Bench containing this Hala checkout.' >&2
        exit 1
    fi
    HALA_BENCH_DIR="$(dirname -- "$HALA_BENCH_DIR")"
done
cd "$HALA_BENCH_DIR"

hala_build=0
hala_check=0
for hala_option in "$@"; do
    case "$hala_option" in
        --build) hala_build=1 ;;
        --check) hala_check=1 ;;
        --help)
            echo 'Usage: bash apps/hala/scripts/start-hala-wsl.sh [--build] [--check]'
            echo '  --build  Rebuild Hala assets before starting Bench.'
            echo '  --check  Start/check the database, optionally build, then exit without starting Bench.'
            exit 0
            ;;
        *) echo "Unknown option: $hala_option" >&2; exit 2 ;;
    esac
done

./env/bin/python - <<'PY'
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import MySQLdb


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Run as your normal WSL user (nagi), without sudo.')
    bench = Path.cwd()
    directory = bench / 'config' / 'helohala_mariadb'
    data = directory / 'data'
    endpoint = directory / 'mysql.sock'
    config = json.loads((bench / 'sites' / 'common_site_config.json').read_text())
    config.update(json.loads((bench / 'sites' / 'helohala.localhost' / 'site_config.json').read_text()))
    if Path(config.get('db_socket') or '') != endpoint:
        raise RuntimeError('Hala database socket configuration differs from this local instance.')
    if not (data / 'ibdata1').is_file():
        raise RuntimeError('Existing Hala database files are missing; no new database was created.')

    def listening():
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            try:
                connection.connect(str(endpoint))
                return True
            except OSError:
                return False

    # Serialize startup attempts so two terminals cannot launch the same datadir twice.
    with (directory / 'startup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not listening():
            with (directory / 'server.out').open('a') as output:
                process = subprocess.Popen([
                    '/usr/sbin/mariadbd', '--no-defaults',
                    f'--datadir={data}', f'--socket={endpoint}',
                    f'--pid-file={directory / "mysql.pid"}',
                    f'--log-error={directory / "error.log"}',
                    '--skip-networking', '--character-set-server=utf8mb4',
                    '--collation-server=utf8mb4_unicode_ci',
                ], stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                    start_new_session=True)
            deadline = time.monotonic() + 30
            while not listening():
                if process.poll() is not None:
                    raise RuntimeError(f'MariaDB stopped during startup. See {directory / "error.log"}.')
                if time.monotonic() >= deadline:
                    process.terminate()
                    process.wait(timeout=5)
                    raise RuntimeError(f'MariaDB startup timed out. See {directory / "error.log"}.')
                time.sleep(0.25)
            print(f'Started existing Hala MariaDB (PID {process.pid}).')
        else:
            print('Hala MariaDB is already running.')

        # Use the configured site credentials without printing or changing them.
        connection = MySQLdb.connect(
            user=config.get('db_user') or config['db_name'],
            passwd=config['db_password'], db=config['db_name'],
            unix_socket=str(endpoint), charset='utf8mb4', connect_timeout=5,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                assert cursor.fetchone()[0] == 1
        finally:
            connection.close()
    print('helohala.localhost: database connection verified.')


try:
    main()
except Exception as error:
    raise SystemExit(f'Hala database startup/check failed: {error}')
PY

if (( hala_build )); then
    bench build --app hala
fi

if (( hala_check )); then
    exit 0
fi

./env/bin/python - <<'PY'
import socket

occupied = []
for port in (8000, 9000, 11000, 13000):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        if connection.connect_ex(('127.0.0.1', port)) == 0:
            occupied.append(str(port))
if occupied:
    raise SystemExit('Bench ports already in use: ' + ', '.join(occupied)
        + '. Stop the existing Bench/standalone processes before starting another Bench.')
PY

echo 'Starting Bench. Open http://helohala.localhost:8000/desk/hala-booking'
exec bench start
