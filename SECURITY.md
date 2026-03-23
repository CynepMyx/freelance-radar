# Security Policy

## Credentials

- Never commit `app.env` — it contains your Kwork password and Telegram token
- The `data/` directory holds a Kwork session token — keep your server secure
- Restrict access to your VPS and the `data/` directory

## Reporting a Vulnerability

If you find a security issue, please open a GitHub issue or contact the maintainer directly. Do not include credentials or sensitive data in bug reports.

## Notes

- The Kwork integration uses an unofficial mobile API. Credentials are sent to `api.kwork.ru` over HTTPS.
- Telegram notifications may contain project descriptions with client contact info — treat them accordingly.
