# Local Hala startup in WSL

This launcher is for the existing `helohala.localhost` development site whose
MariaDB data directory is `config/helohala_mariadb/data` and whose configured
socket is `config/helohala_mariadb/mysql.sock`, relative to the Bench directory.
It does not provision a site or initialize a database.

Run as your normal WSL user, without `sudo`:

```bash
cd /home/nagi/my-bench
bash apps/hala/scripts/start-hala-wsl.sh
```

The script locates its containing Bench, starts the existing MariaDB instance
only when its socket is unavailable, and verifies a connection using the site's
configured credentials. It does not print credentials. A startup lock prevents
two copies of the launcher from starting the same data directory concurrently.

After checking that the standard Bench ports are available, it runs `bench start`
in the foreground. Keep the terminal open. Open
`http://helohala.localhost:8000/desk/hala-booking`. Press Ctrl+C to stop Bench;
the separate MariaDB instance remains running.

The local `development/start-hala-wsl.sh` shortcut can continue to forward to this
version-controlled script in an existing workspace.

## Options

```bash
# Start/check the database and exit without launching Bench.
bash apps/hala/scripts/start-hala-wsl.sh --check

# Rebuild Hala assets, then launch Bench.
bash apps/hala/scripts/start-hala-wsl.sh --build

# Start/check the database and rebuild Hala without launching Bench.
bash apps/hala/scripts/start-hala-wsl.sh --build --check
```

Building while Redis is stopped may report that `redis_cache` cannot be reached
to refresh `assets_json`. Start Bench to restore Redis. Avoid launching another
Bench while its existing processes still occupy ports 8000, 9000, 11000 or 13000.

## Database connection errors

If the site reports `MySQLdb.OperationalError (2002)` for the configured socket,
check whether this separate MariaDB instance is running. Starting the system
MariaDB service uses a different data directory/socket and does not start this
instance.

In the inspected Frappe version, a database failure during `frappe.init` can also
cause `AttributeError: is_ajax`: request initialization fails before that flag
is assigned, and the exception handler then tries to read it. Restoring the
database resolves the triggering failure. This launcher does not patch Frappe
core or change application, accounting, inventory or payment behavior.

If MariaDB fails to start, inspect `config/helohala_mariadb/error.log`. The
launcher does not delete database files, repair tables, or change site settings.
