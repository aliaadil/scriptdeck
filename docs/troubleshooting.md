# Troubleshooting

- **Container is unreachable:** publish `8765:8765` and confirm `KINDLING_HOST=0.0.0.0`.
- **Authentication always fails:** `KINDLING_BASIC_AUTH` requires `username:bcrypt_hash`, not plaintext.
- **Data disappears:** mount persistent storage at both `/data` and `/storage`.
- **Permission denied:** mounted directories must be writable by UID/GID 10001.
- **Import skips rows:** inspect warning logs; ensure both JSON files are arrays and script languages are Python, JavaScript/Node, or Bash/Shell.
- **Health check fails:** inspect container logs for startup errors.
