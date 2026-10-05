# Windows authentication smoke test

Run on the branch build, not an unmodified v10.5.125 executable. The automated
lifecycle tests use mocked browser/history calls and do not prove provider login,
Win32 window closure, or session persistence. Never commit credentials, cookies,
OAuth codes, or unredacted callback URLs.

## Outlook (required before claiming the issue is resolved)

1. Record build commit, Windows version and Chromium version. Use a disposable
   Tekzite profile/account where available; sign out for the fresh-login case.
2. Start from Microsoft's Outlook product page and follow its sign-in link.
3. Complete login in the separate Chromium window, including MFA if required.
4. Verify the mailbox loads before the auth window disappears automatically.
   Record whether it closes without clicking X and the elapsed time.
5. Verify Tekzite resumes a working page. If it returns to the initiating product
   page, open Outlook mail from there. Confirm the mailbox is authenticated and
   belongs to the expected account; do not accept a URL or title as evidence.
6. Reload, then close and reopen Tekzite. Confirm the session remains usable.
7. Repeat with an existing SSO session.
8. Repeat but close the auth window before completing login. Confirm Tekzite
   resumes the initiating page without claiming success or replaying a callback.

## GitHub OAuth, Auth0 and Okta

Use a controlled relying application with a registered callback. Repeat steps
3–8 for each provider. For GitHub approve and deny consent; for Auth0 use a
code/PKCE application; for Okta include MFA. Confirm the relying application's
protected page/API works after Tekzite reopens the profile, not merely that the
identity provider has a session. Include an application storing auth state in
web storage and identify whether that storage survives the handoff.

## Failure checks with a controlled relying application

- Return `error=access_denied` in query and fragment: no success-triggered close.
- Reject state mismatch, expired/reused code or callback server error: record
  whether Tekzite closes too early. Application failures without an OAuth error
  URL are a remaining gap in history-based completion detection.
- Change a consent/CSRF cookie while login is pending: window stays open.
- Delay callback processing and cookie flush; keep profile ownership active:
  embedded Chromium must not restart until profile release.
- Switch tabs or close the initiating tab during login: no other tab receives
  the result, and the interface remains usable.

Record PASS/FAIL/NOT RUN for every case, with build commit and timing. A failure
must include only sanitized paths/error names and user-visible behavior.
