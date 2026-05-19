# Manual Simulator Usage

Use this workflow when you want to start a simulated `lmgrd` daemon yourself, manually check out and return licenses, and view usage with `lmstat`.

The simulator exposes HTTP endpoints for checkout/checkin operations. `lmstat` reads those endpoints and prints FlexNet-style text to the screen.

## Create A License File

Create a small simulator license file:

```bash
cat > /tmp/license.dat <<'EOF'
SERVER_NAME lic_server_1
PORT 27000
FEATURE alpha 2 EXP 2026-11-01
FEATURE beta 1
EOF
```

Supported license-file lines:

- `SERVER_NAME <name>`: optional display name for the simulated server.
- `PORT <port>`: required HTTP/listener port for the simulator.
- `DAEMON <name>`: optional vendor daemon name.
- `FEATURE <name> <total>`: feature name and license count.
- `FEATURE <name> <total> DAEMON <daemon> EXP <YYYY-MM-DD>`: optional daemon and expiration. `lmstat -i` renders expiration as `DD-Mon-YYYY`, for example `01-Nov-2026`.

## Start lmgrd

Start the daemon in one terminal:

```bash
conda run -n venv312_license_manager simulators/wrappers/lmgrd \
  -c /tmp/license.dat \
  -l /tmp/lmgrd.log
```

The process runs until you stop it with `Ctrl-C`. The simulated daemon listens on the `PORT` from the license file.

Check health from another terminal:

```bash
curl -s http://127.0.0.1:27000/v1/health
```

## Check Out A License

Use the checkout endpoint to request one license for a feature:

```bash
curl -s -X POST http://127.0.0.1:27000/v1/checkout \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id": "checkout-1",
    "feature": "alpha",
    "user": "user1",
    "host": "host1",
    "pid": 101
  }'
```

Example response:

```json
{
  "checkout_id": "<uuid>",
  "feature": "alpha",
  "status": "GRANTED",
  "reason": null,
  "total": 2,
  "in_use": 1,
  "queued": 0
}
```

Save the returned `checkout_id`; you need it to return the license.

If all licenses for a feature are already in use, the simulator returns `status: "QUEUED"` and keeps the request in the feature queue.

## Return A License

Return a license by posting the `checkout_id` from the checkout response:

```bash
curl -s -X POST http://127.0.0.1:27000/v1/return \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id": "return-1",
    "checkout_id": "<uuid-from-checkout>"
  }'
```

When a granted license is returned and the feature has queued requests, the simulator grants the next queued checkout for the same feature.

## Show Usage With lmstat

Print all feature usage to the screen:

```bash
conda run -n venv312_license_manager simulators/wrappers/lmstat -c 27000@127.0.0.1 -a
```

Print all feature usage with checkout details:

```bash
conda run -n venv312_license_manager simulators/wrappers/lmstat -c 27000@127.0.0.1 -a -i
```

Print one feature with details:

```bash
conda run -n venv312_license_manager simulators/wrappers/lmstat -c 27000@127.0.0.1 -f alpha -i
```

`lmstat` writes FlexNet-style output to stdout. Example detail rows include granted and queued checkout records:

```text
Users of alpha:               (Total of 2 licenses issued;  Total of 1 license in use)

  "alpha" v1.0, vendor: default, expiry: 01-Nov-2026
  floating license

    "user1" host1 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start Sun 5/10 08:40

NOTE: lmstat -i does not give information from the server,
      but only reads the license file.  For this reason,
      lmstat -a is recommended instead.

Feature                         Version     #licenses    Expires      Vendor
_______                         _________   _________    __________   ______
alpha                           1.0         2           01-Nov-2026  default
```

Returned checkouts are excluded from `lmstat -i` detail output.

## Useful Debug Endpoints

Get JSON feature status:

```bash
curl -s http://127.0.0.1:27000/v1/status
```

List checkout records:

```bash
curl -s 'http://127.0.0.1:27000/v1/debug/checkouts?limit=20'
```

List only active granted checkouts:

```bash
curl -s 'http://127.0.0.1:27000/v1/debug/checkouts?status=GRANTED'
```

List queued requests:

```bash
curl -s 'http://127.0.0.1:27000/v1/debug/queue?limit=20'
```

## Stop lmgrd

Stop the foreground `lmgrd` process with `Ctrl-C`.

The activity log remains at the path passed with `-l`, for example `/tmp/lmgrd.log`.
