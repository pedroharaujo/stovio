# MVP privacy publication checklist

Use this checklist for the exact Android release candidate.

## Publication status — 2026-09-27 (#193)

The founder approved publishing the privacy policy and account-deletion page
for testing on 2026-09-26 (#193), without waiting for legal review. The
[`site/`](../../site/) pages are prepared for the `Public pages` workflow to
publish on merge to `main`:

- Privacy policy: <https://pedroharaujo.github.io/stovio/privacy/>
- Account deletion: <https://pedroharaujo.github.io/stovio/delete-account/>

Read-only setup checks on 2026-09-27 confirmed that GitHub Pages already uses
the Actions source with HTTPS. Both public URLs still returned 404 before merge;
publication and signed-out URL verification remain unchecked. Play Console now
marks Sign in details complete (5 of 11 setup tasks complete), superseding the
earlier reviewer-details save failure. No credentials or release were submitted
during this check.

The text distinguishes current account and device-linked guest history from
approved D-020 retention targets that are not yet enforced or verified. It
does not establish an 18+ account rule, verified transfer safeguards, universal
App Check enforcement or completed provider deletion. The existing purpose and
legal-bases wording is retained for the founder-authorized test publication; it
has not had legal review. These factual corrections remain within #193's
publication authorization.

The unchecked items below remain release work, including financial-record
periods, age-related requirements, provider roles/transfers, AdMob SDK removal,
inactivity notice, receipt expiry, guest-history expiry/erasure and provider
cleanup. Publishing the pages does not prove store acceptance or authorize
production activation. Update them whenever the binary, providers or retention
behavior change.

## Decisions and legal review

- [ ] Before production activation, complete review of the purpose-to-legal-basis
  mapping, legitimate-interest analysis, user contract boundary and consent wording.
- [ ] Resolve age-related requirements under D-003/D-035 against the intended
  audience and catalog. No minimum account age is established by these pages.
- [x] Founder approves the discretionary retention defaults for profiles,
  progress, analytics, routine logs, support mail, backups and deletion receipts
  (2026-09-20; [D-020 partial decision](MVP_RETENTION_DECISION.md)).
- [ ] Implement and verify those defaults on the exact release, including
  inactivity notice, purchased-access preservation, pending-cleanup/recovery
  protections, provider-controlled log exceptions and backup restore behavior.
- [ ] Approve the lawful basis, exact retained fields, access controls and
  deletion/anonymization period for detached wallets, coin ledgers, purchase
  decisions/events and unlock/cancellation receipts, including refund,
  chargeback, tax, fraud and dispute needs (D-020 and unresolved D-008 terms).
- [x] Founder supplied **Pedro Henrique Araujo Pinto, individual**, and the
  public support/privacy contact in #144 on 2026-09-20.
- [ ] Determine whether applicable law requires a public postal address or other
  registration/contact information. Do not invent a company or address.
- [ ] Confirm the rights-request process, identity-verification steps, response
  ownership and CNIL/other-authority wording.

## Providers and data inventory

- [ ] For the exact release binary, record every SDK/service and its observed
  data behavior: Firebase Authentication, App Check and Analytics; Google Play;
  RevenueCat; Bunny Stream; Gmail; backend/database/hosting; notice/deletion-page
  hosting; logging, monitoring, backups and any content-delivery subprocessors.
- [ ] Approve each provider's controller/processor role, contract or DPA,
  processing locations, subprocessors and any transfer mechanism. Do not claim
  EU-only processing unless verified.
- [ ] Verify provider deletion, backup and late-event lifecycles. In particular,
  confirm Firebase deletion retries, RevenueCat/Google Play purchase retention,
  Bunny logs, Gmail support mail, analytics deletion, and that delayed purchase
  events cannot recreate or attach to a deleted account.
- [ ] Confirm rewarded ads and their data collection are absent/disabled in the
  exact coin-only MVP binary (D-037). Remove dormant ad disclosures from the
  final notice unless the shipped SDK behavior still requires them.

## Deletion and user-facing publication

- [ ] Publish a working, public, non-geofenced HTTPS privacy-policy page (not a
  PDF), mark it “Privacy policy,” add the effective date, and verify the operator
  name matches the Google Play listing.
- [ ] Publish a working external account-deletion page that names the app and
  lets a user request account and associated-data deletion without reinstalling
  the app. State current retained categories and reasons, distinguish unverified
  targets, and avoid an unapproved financial-record expiry promise.
- [ ] Verify the in-app deletion path on the exact binary, including recent
  reauthentication, pending Firebase cleanup, provider propagation and the
  user's accurate completion message.
- [ ] Provide and test a separate guest-progress deletion path. Account deletion
  and clearing device storage do not erase existing server-held guest history.
- [ ] Test both public URLs without signing in, from France and outside it, then
  enter the final privacy and deletion URLs in Play Console.

## Exact release consistency

- [ ] Compare the final notice, Play Data safety form, consent screens,
  permissions, store listing and in-app controls against the exact signed
  Android artifact and production configuration.
- [ ] Enable and verify Firebase App Check for the release environment under
  issue #122 before describing it as active protection.
- [ ] Confirm analytics starts only after the recorded opt-in and stops/clears
  identity when switched off, signed out or deleted; document the approved
  treatment of provider-held historical events.
- [ ] Confirm support/privacy mail reaches
  [pharaujo1094@gmail.com](mailto:pharaujo1094@gmail.com), is monitored, and the
  app never automatically includes credentials, receipts, raw provider data,
  hidden account IDs or diagnostics.
- [ ] Archive the published testing version and date with the founder's #193
  authorization; complete remaining privacy review and exact-release verification
  before production activation.
- [ ] Re-run this checklist whenever the binary, SDKs, providers, data flows,
  countries, monetization, or public operator details change.

## Support handoff verification (P6-T03)

The automated UI checks cover draft encoding, handoff failure, account-change
isolation and unchanged purchase/unlock actions. These native/mailbox observations
remain deferred under D-029; they are not passed checks:

1. Open Account while signed out and while the API is unavailable. Open Help &
   Support; confirm the operator, selectable address and email action are visible.
2. Tap Email support on Android. Confirm the email app opens an editable draft
   addressed to the public inbox. Nothing is sent without pressing Send there.
3. On an existing unresolved purchase or unlock, inspect the draft: it includes
   only the displayed support reference and generic instructions, not credentials,
   hidden account identifiers, diagnostics or provider receipts. Do not create a
   new purchase just to repeat this check. Changing accounts must hide the old
   reference and action.
4. With no email handler available, confirm the visible address/reference can be
   selected and copied and the failure message permits retry. Confirm opening the
   draft does not resolve a purchase, erase recovery state or spend coins.
5. Open "Privacy policy" from Account without signing in. It must open the
   published page above in the browser.
6. With the founder's authorization, send a non-sensitive test message and verify
   receipt and reply. A displayed address is not delivery or monitoring evidence.

Support references locate records; they are not proof of account ownership.
Verify the requester through an approved account-ownership process before
disclosing private history or acting on a request. Do not ask for passwords,
verification codes or payment-card details, and do not modify accounting history
or clear an ambiguous purchase based only on an email. Financial resolution and
refund policy remain separate approval gates in #144 and #164.
