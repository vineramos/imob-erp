# Security policy

This repository is public, but production data and production credentials are not.

## Never commit

Do not commit any of the following, even temporarily:

- `.env` files containing real values;
- database connection strings;
- GitHub access tokens;
- Google Cloud service-account JSON keys;
- private keys, client certificates, P12/PFX/JKS files;
- Clicksign access tokens or webhook secrets;
- Banco Inter client secrets, certificates or private keys;
- SMTP passwords;
- WhatsApp access tokens, app secrets or webhook verification secrets.

Use GitHub repository variables only for non-secret deployment metadata. Store production secrets in the runtime environment or Google Secret Manager.

## Public-history rule

Deleting a secret in a later commit does not remove it from a public Git history. If a real credential is ever committed:

1. revoke or rotate the credential immediately;
2. remove it from every reachable Git commit;
3. force-update the affected refs only after the credential has been revoked;
4. re-run the public repository safety check;
5. review deployment and audit logs for unauthorized use.

The CI job `public-safety` scans reachable Git blobs for common credential artifacts and known high-risk token signatures.

## Vulnerability reports

Do not open a public issue containing credentials, personal data, production database contents or an exploitable proof-of-concept against the live ERP.

Prefer GitHub's private vulnerability-reporting / security-advisory flow when it is enabled for this repository. Otherwise contact the repository owner privately before publishing sensitive technical details.

## Operational boundaries

The repository may contain architecture, endpoint names, migration structure and non-secret infrastructure conventions. These are not authentication factors. Production access must continue to depend on identity, authorization and secret material held outside Git.
