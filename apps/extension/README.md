# Command Center Companion

Start the API on localhost:8000 and web app on localhost:3001. In Chrome's Extensions page, enable Developer mode and Load unpacked → this directory. Open the workspace's Browser companion page, create a pairing code, and paste it into the extension popup.

Open an application form and click **Share this form**. Prepare values in the workspace, then click **Check fill proposals** in the popup. Review the values and apply. Pairings are one-use and expire in five minutes; device credentials can be revoked in the workspace. The popup stores only its revocable device credential in extension storage restricted to trusted extension contexts.

This first slice supports visible text/email/telephone/URL inputs, textareas and single selects in the top frame. It excludes passwords, payment/SSN fields, hidden controls, uploads and radio/checkbox controls. It does not read cookies or existing field values and does not submit. A proposal is tied to the exact live document snapshot; stale pages require a fresh share. Claimed or uncertain actions never replay automatically.

For the controlled test form, open http://localhost:3001/fixtures/application.html. All data on that page is fictional. Remote API deployments need an explicit host-permission and HTTPS configuration change.

HTTP payloads and the versioned popup/content messages are defined in `apps/api/src/command_center/api/browser_contracts.py`. Run `make contracts` after schema changes; this generates Next.js types and the bundled `contracts.js` runtime validators. Both sides reject incompatible/malformed messages before filling. Validators are compiled ahead of time for Manifest V3 (no eval or remote code). Reload the unpacked extension after updates. `make contracts-check` catches drift and `make test-browser` starts its own synthetic fixture server on port 4319.
