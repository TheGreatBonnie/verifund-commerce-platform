# Verifund Seller Fulfillment Workspace — UI structure

The Seller Fulfillment Workspace should be a dedicated area of Verifund where sellers manage everything required to fulfill an approved transaction: reviewing obligations, submitting evidence, responding to verification requests, and monitoring fulfillment progress.

It should feel like an order fulfillment and evidence-management workspace, not a generic seller dashboard and not just a file-upload form.

The key design principle is:

The agreement defines what the seller must do; the workspace guides the seller through doing it and proving it.

I recommend designing it around two connected experiences:

1. Seller Dashboard: an overview of all orders that require fulfillment, evidence submission, or seller action.
2. Transaction Fulfillment Workspace: a dedicated workspace for one transaction, with its agreement, fulfillment checklist, evidence uploads, verification results, and activity history.

The same transaction workspace should be accessible through the seller's dashboard or an authenticated, transaction-specific link sent by the Seller Agent through the seller's preferred messaging platform.

## 1. Overall navigation and information architecture

[Order Creator for B2B Businesses | Two Payment Solutions](https://images.openai.com/static-rsc-4/-u08cWJ4c9ZaDCnTKxDVD-MDhD43yCuVQ1cMXEyuMUkR8yaUbgxar12C2Luk1LAELHufrOi92CupqA8MvyrYBgtvvaUvDnnFyvusACtZTXwlBHPV1RdLYJDD2UZY9PNRYaQPBDx2Wj9Fb5Q-OAtxolwdFRHOM6kk3niR7NteyRk?purpose=inline)

[two.inc](https://www.two.inc/products/order-creator?utm_source=chatgpt.com)

The seller dashboard should have a relatively simple navigation structure.

| Navigation  | Purpose                                                          |
| ----------- | ---------------------------------------------------------------- |
| Overview    | Fulfillment summary and tasks needing attention                  |
| Orders      | All seller transactions                                          |
| Fulfillment | Orders requiring shipment, service delivery, or evidence         |
| Evidence    | Submitted evidence and verification status                       |
| Messages    | Communication with Buyer Agent and Verifund                      |
| Payouts     | Payment and payout status                                        |
| Settings    | Seller profile, connected channels, and notification preferences |

I would make Fulfillment the primary workspace entry point because it is where the seller takes action after an order is approved and payment is processed.

### Seller dashboard overview

The dashboard should show four summary metrics:

Awaiting fulfillment

# 08

Approved orders

Evidence required

# 05

Need seller submission

Under verification

# 03

Being reviewed by Verifund

Needs attention

# 02

Remediation or review required

Below the metrics, show a Fulfillment Tasks table.

| Transaction | Order               | Required action          | Status             |
| ----------- | ------------------- | ------------------------ | ------------------ |
| VF-2048     | Refurbished laptop  | Submit product evidence  | Evidence required  |
| VF-2051     | Website development | Submit deliverables      | In progress        |
| VF-2054     | Wireless headphones | Submit tracking          | Under verification |
| VF-2057     | API integration     | Resolve evidence request | Needs attention    |

Each row should open the corresponding transaction workspace.

## 2. Transaction Fulfillment Workspace

This is the most important screen. When a seller opens a fulfillment task, they should land on a transaction-specific page rather than a generic upload screen.

I recommend a three-column desktop layout, adapting to stacked sections on mobile:

SELLER WORKSPACE / FULFILLMENT

Transaction VF-2048

Evidence required

[HP EliteBook 840 G7 14" Refurbished Laptop, Intel Core i7-10610U 1.8GHz, 32GB RAM, 1TB SSD, Windows 11 Pro (J5-840G7A07) | Staples](https://images.openai.com/static-rsc-4/1hA1pDGWIN0UD5DC7oC3WIQNmf5Vr4Z1aJT2GoptzEq1SzoWwriPDLshvYqrXcwXrbJTrT59W4fodw9UhYBM2ZkLFselSwvGT5DQEukT3TBWH1TPek5kzSFJ1xM194pzxLL7INuOm8l0OkHIOdYZVqDnwlT257GTfRiLLSF5ZWA?purpose=inline)

Refurbished AI-development laptop

Buyer: Maya Chen · Quantity: 1

# $1,400.00

Approved agreement · Version 1

Fulfillment progress

2 of 5 requirements submitted

40%

Hardware specifications

Diagnostic report submitted

Submitted

Warranty documentation

90-day warranty document submitted

Submitted

Product photographs

Upload photographs of the actual laptop

Required

Serial number

Provide a clear photograph of the identifier

Required

Shipping information

Carrier and tracking number

Required

Payment processed · Internal state recorded

Confirmed

Illustrative workspace preview, not a live transaction.

The screen should contain five major areas.

### A. Transaction header

At the top, display:

- Transaction ID.
- Product or service name.
- Buyer identity or approved display name.
- Agreement version.
- Order amount and currency.
- Fulfillment status.
- Payment processing status.

The seller should immediately understand which transaction they are working on.

Include a button to open the full agreement. The seller must be able to inspect the obligations they accepted during negotiation.

### B. Agreement and fulfillment summary

Show the requirements extracted from the approved agreement.

For the laptop example:

| Agreement requirement | Seller obligation                 |
| --------------------- | --------------------------------- |
| Product               | Refurbished laptop                |
| RAM                   | 32 GB minimum                     |
| Storage               | 1 TB SSD                          |
| Warranty              | 90 days                           |
| Shipping              | Tracked delivery                  |
| Inspection            | 48 hours after confirmed delivery |

This section should be read-only. The seller should not be able to edit contractual requirements from the fulfillment workspace.

If the seller and buyer agree to change a material term, that change must go through the appropriate agreement revision and approval process.

### C. Evidence checklist

This should be the main working area.

Each requirement should appear as an individual evidence card, rather than combining every document into one upload field.

Each card should display:

- Requirement name.
- Explanation of what the seller needs to provide.
- Accepted evidence formats.
- Whether evidence is mandatory.
- Submission status.
- Verification status.
- Upload or replacement action, where permitted.

For example:

Product photographs

Required

Upload photographs showing the actual laptop from multiple angles. Include the screen, keyboard, exterior, and any visible damage.

JPG

PNG

WEBP

Video

Drag files here or select files

Multiple files · Upload limits configured by Verifund

Explore upload component

Evidence is associated with VF-2048 and agreement version 1.

A seller should be able to upload evidence directly into the relevant requirement card. This makes it much harder to submit a document without explaining which contractual obligation it supports.

### D. Verification status

After submission, the evidence card should change to show its verification progress.

For example:

- `UPLOADED` — Verifund has received the file.
- `PROCESSING` — Integrity checks and extraction are running.
- `UNDER_REVIEW` — Verification is in progress.
- `VERIFIED` — The requirement passed its checks.
- `ACTION_REQUIRED` — Additional evidence or clarification is needed.
- `REJECTED` — The evidence failed the defined checks.

Do not use a single overall status to hide the state of individual evidence items. One requirement can be verified while another remains under review.

### E. Activity and communication

Include a timeline of important events:

- Fulfillment task created.
- Seller notified.
- Evidence uploaded.
- Evidence verification started.
- Additional evidence requested.
- Evidence approved or rejected.
- Delivery confirmed.
- Buyer inspection started.

The seller should be able to respond to requests without leaving the workspace.

## 3. Evidence submission experience

The upload interaction should be guided by the selected agreement requirement.

I would use a modal or side panel when the seller selects Submit evidence.

Submit evidence

VF-2048

Agreement requirement

Serial number verification

Provide a clear photograph showing the laptop's serial number.

Evidence type

Image or document

Upload photograph

Choose an image from your device

Evidence description

Explain what this evidence demonstrates.

Photograph of the serial number on the laptop's underside.

Source information

Optional context, such as diagnostic tool or issuing organization.

Illustrative interaction

The submission form should collect:

1. Requirement association: Which agreement requirement does this submission address?
2. Evidence type: Image, video, PDF, document, URL, tracking reference, or another supported type.
3. Evidence file or reference: The actual upload or external source.
4. Description: What the evidence demonstrates.
5. Source details: Where it came from, if applicable.

For service deliverables, the upload form should also support external links such as GitHub pull requests, deployment URLs, and Figma files.

### One requirement can have multiple evidence items

For example, proving a laptop's hardware specifications might require:

- A system information screenshot.
- A diagnostic report.
- A short video showing the device.

The UI should let sellers attach multiple evidence items to the same requirement. Each submission should retain its own verification result.

## 4. How the workspace maps to Verifund's seven-step workflow

The UI should reflect the backend workflow rather than making the seller figure out what happens next.

1. Payment confirmation

   The workspace becomes available after Verifund receives the relevant payment-provider confirmation and records the appropriate internal payment state.

   The seller sees a payment status such as `Payment processed`, with a clear explanation of what that status means. Do not display `Funds secured in escrow` unless the actual payment arrangement supports that claim.

2. Fulfillment task creation

   Verifund creates a task from the approved agreement. The workspace displays the exact product or service, required obligations, due dates, and evidence checklist.

   The seller sees what needs to be done before starting.

3. Seller Agent notification

   The Seller Agent sends a notification through the seller's connected messaging channel.

   For example: "Your order VF-2048 is ready for fulfillment. Open your secure workspace to review the requirements and submit evidence."

4. Evidence upload

   The seller uploads files, images, videos, tracking details, or service deliverables.

   Upload progress, file validation, and submission errors should be visible.

5. Requirement association

   The seller selects the relevant agreement requirement for each submission. If the seller opened the upload form from a requirement card, that requirement should already be selected.

   This association is essential for automated verification.

6. Evidence storage and verification task creation

   After a successful upload, Verifund stores the evidence and creates a verification task.

   The UI immediately changes the evidence status to `Submitted` or `Processing`. It should not show `Verified` until the verification service has actually completed its checks.

7. Submission receipt and progress monitoring

   Verifund generates a submission receipt containing the evidence IDs, submission timestamp, transaction ID, agreement version, and initial processing status.

   The seller can return to the workspace to monitor the verification results and respond to requests for additional evidence.

Explain Personal AI Agents.txt

Explain Personal AI Agents.txt

## 5. Accessing the workspace through messaging platforms

This is a particularly important part of Verifund's design because the seller may not regularly use the Verifund dashboard.

The seller should be able to initiate and monitor fulfillment from the platform they already use, while the actual evidence submission happens in a secure Verifund web workspace.

I recommend supporting two entry points.

### A. Seller dashboard entry

The seller logs into Verifund, opens Fulfillment, and selects the relevant transaction.

```
Seller Dashboard
    |
    v
Fulfillment Tasks
    |
    v
Transaction VF-2048
    |
    v
Fulfillment Workspace
    |
    v
Submit Evidence
```

This is the normal authenticated application flow.

### B. Messaging platform entry

The Seller Agent sends a transaction-specific link.

For example:

Seller Agent

Direct message · Just now

New task

Your order is ready for fulfillment.

Transaction: VF-2048

Product: Refurbished AI-development laptop

Required evidence:

- Product photographs
- Serial number photograph
- Hardware diagnostic report
- Warranty documentation
- Shipping tracking information

Please open your secure fulfillment workspace to submit the required evidence.

Secure Verifund workspace

Authenticated transaction access · VF-2048

Example link: `https://verifund.example/fulfillment/access/...`

The link should take the seller to the transaction-specific workspace, not directly to an unrestricted upload endpoint.

### How authenticated links should work

I recommend a secure link exchange:

1. Verifund creates a transaction-specific access invitation.
2. The Seller Agent sends the invitation through the seller's connected messaging channel.
3. The seller opens the link.
4. Verifund validates the token and checks the seller's identity.
5. If the seller is not authenticated, Verifund requests login or an appropriate identity verification step.
6. Verifund checks that the authenticated seller is authorized for that transaction.
7. The seller is redirected to the fulfillment workspace.

Important security rules:

- Use short-lived, high-entropy, single-purpose access tokens.
- Bind the invitation to the seller account, transaction, and permitted actions.
- Do not place sensitive transaction data in the URL.
- Do not treat possession of a forwarded link as proof of seller identity.
- Allow revocation and reissuance.
- Record link usage and access attempts.
- Require stronger authentication for sensitive actions.

The link can identify the intended workspace, but the server must still authorize every upload and transaction operation.

### Messaging should complement the workspace, not replace it

The messaging platform should support:

- Fulfillment notifications.
- Requirement reminders.
- Verification updates.
- Requests for additional evidence.
- Links to review evidence or resolve issues.
- Submission receipt notifications.

The actual file storage, verification status, and transaction record should remain authoritative in Verifund.

For a seller using Slack, Discord, or another supported messaging platform, the experience should be consistent even though the notification interface differs.

## 6. Submission receipt and verification progress

After the seller submits evidence, Verifund should show a confirmation screen and send a receipt through the connected messaging channel.

Evidence submitted

Your submission has been received by Verifund.

Received

SUBMISSION RECEIPT

# SUB-00821

Transaction VF-2048 · Agreement v1

| Submission detail | Value                      |
| ----------------- | -------------------------- |
| Evidence item     | Serial number photograph   |
| Requirement       | Serial number verification |
| Submitted by      | NovaTech Renewed           |
| Submitted at      | 04 Nov 2026, 10:30         |
| Initial status    | Processing                 |

Verification progress

Verification task

Processing

Verifund will notify you when the evidence has been reviewed or if additional information is needed.

The receipt should be generated only after the file has been successfully stored and the submission record has been committed.

It should not imply that the evidence has been approved.

### Evidence progress screen

The seller should also have an Evidence tab inside the transaction workspace.

| Evidence             | Submission    | Verification      |
| -------------------- | ------------- | ----------------- |
| Product photographs  | Submitted     | Verified          |
| Serial number        | Submitted     | Under review      |
| Hardware report      | Submitted     | Verified          |
| Warranty document    | Submitted     | Verified          |
| Tracking information | Not submitted | Awaiting evidence |

The seller can see which items are complete, which are being processed, and which need attention.

When verification fails or requires clarification, the workspace should explain what needs to change.

For example:

Additional evidence required

Action required

The serial number photograph is too blurry to read.

What to do: Upload a clearer photograph showing the full serial number on the device.

The previous submission remains in the audit history. Upload a replacement to continue verification.

This creates a clear remediation loop instead of forcing the seller to contact support whenever an upload is insufficient.

## 7. Recommended page structure

I would organize the transaction workspace into these tabs:

## VF-2048 · Fulfillment Workspace

OverviewEvidenceActivity

Overview

- Transaction summary and approved agreement.
- Payment processing status.
- Fulfillment progress.
- Required obligations and deadlines.
- Outstanding seller actions.
- Quick link to submit evidence.

I would also keep the agreement accessible from the header rather than making it a separate tab. Sellers should be able to check the exact obligations at any time.

### Desktop layout

The desktop workspace should have three visual zones:

Transaction header

In fulfillment

Order details · Agreement · Payment status

Order details

Product / service

Agreement terms

Deadlines

Buyer details

Evidence checklist

Verified

Product specifications

Required

Product photographs

Processing

Serial number

Upload evidence

Activity

Task created

Evidence submitted

Verification started

Seller notified

Conceptual layout showing the hierarchy, not a pixel-perfect mockup.

On mobile, these zones should become stacked sections, with a persistent bottom action such as Submit evidence or Resolve outstanding request.

## 8. Important UI states to design

The workspace should adapt to the transaction's lifecycle.

| State                           | What the seller sees                                        |
| ------------------------------- | ----------------------------------------------------------- |
| `AWAITING_PAYMENT_CONFIRMATION` | Payment is being confirmed; fulfillment actions unavailable |
| `FULFILLMENT_REQUIRED`          | Task created; review agreement and requirements             |
| `EVIDENCE_REQUIRED`             | Checklist and upload actions                                |
| `EVIDENCE_SUBMITTED`            | Submission receipt and processing status                    |
| `UNDER_VERIFICATION`            | Evidence being checked                                      |
| `EVIDENCE_REMEDIATION_REQUIRED` | Specific evidence needs replacement or clarification        |
| `FULFILLMENT_VERIFIED`          | Required fulfillment evidence has passed                    |
| `DISPUTE_OPEN`                  | Relevant actions paused; resolution information displayed   |
| `FULFILLMENT_COMPLETED`         | Fulfillment requirements completed                          |

These should be transaction-level states, supported by individual evidence-item states. For example, a transaction can be `UNDER_VERIFICATION` while three evidence items are already `VERIFIED`.

## 9. Backend events that drive the UI

The frontend should not invent its own fulfillment status. It should subscribe to authoritative backend events, using your FastAPI and Next.js architecture with SSE for live updates.

| Event                              | UI response                                 |
| ---------------------------------- | ------------------------------------------- |
| `payment.confirmed`                | Display confirmed payment processing status |
| `fulfillment.task_created`         | Make the fulfillment workspace available    |
| `fulfillment.requirements_created` | Render the agreement-derived checklist      |
| `evidence.submitted`               | Add the submission to the evidence list     |
| `evidence.processing`              | Show processing indicator                   |
| `evidence.verified`                | Update the relevant requirement             |
| `evidence.remediation_required`    | Display a seller action request             |
| `fulfillment.verified`             | Update the overall fulfillment progress     |

The backend should persist these events and the associated records. SSE is a delivery mechanism for updates, not the authoritative transaction database.

## 10. Recommended frontend component structure

For your Next.js 16 + TypeScript + TailwindCSS frontend, I would structure it like this:

```
app/
├── seller/
│   ├── dashboard/
│   │   └── page.tsx
│   ├── orders/
│   │   └── page.tsx
│   ├── fulfillment/
│   │   ├── page.tsx
│   │   └── [transactionId]/
│   │       ├── page.tsx
│   │       ├── evidence/
│   │       │   └── page.tsx
│   │       └── activity/
│   │           └── page.tsx
│   └── evidence/
│       └── page.tsx
│
├── fulfillment/
│   └── access/
│       └── [token]/
│           └── page.tsx
│
components/
├── seller/
│   ├── seller-sidebar.tsx
│   ├── seller-header.tsx
│   ├── fulfillment-summary.tsx
│   ├── fulfillment-task-table.tsx
│   └── seller-stat-cards.tsx
│
├── fulfillment/
│   ├── transaction-header.tsx
│   ├── agreement-summary.tsx
│   ├── fulfillment-progress.tsx
│   ├── requirement-list.tsx
│   ├── requirement-card.tsx
│   ├── evidence-upload-dialog.tsx
│   ├── evidence-file-list.tsx
│   ├── evidence-status.tsx
│   ├── submission-receipt.tsx
│   ├── verification-timeline.tsx
│   └── fulfillment-activity.tsx
│
└── shared/
    ├── file-dropzone.tsx
    ├── status-badge.tsx
    ├── empty-state.tsx
    └── loading-state.tsx
```

## 11. Final product recommendation

I would make the Fulfillment Workspace the seller's central operational interface, with the Seller Agent acting as the communication and guidance layer.

The responsibilities should remain distinct:

| Component              | Responsibility                                                      |
| ---------------------- | ------------------------------------------------------------------- |
| Seller Agent           | Notifies seller, explains requirements, sends reminders             |
| Seller Dashboard       | Lists transactions and outstanding fulfillment tasks                |
| Fulfillment Workspace  | Manages one transaction's obligations and evidence                  |
| Evidence Service       | Stores submissions and manages evidence metadata                    |
| Verification Engine    | Checks evidence against agreement requirements                      |
| Buyer Agent            | Communicates buyer inspection and feedback                          |
| Verifund Policy Engine | Determines whether fulfillment conditions are satisfied             |
| Settlement Coordinator | Executes permitted payment actions and reconciles provider outcomes |

My strongest recommendation is to make the experience requirement-driven, not file-driven. The seller should never wonder what to upload, where to upload it, or why Verifund needs it.

The approved agreement generates the checklist; each checklist item gets its own evidence submissions and verification status; and the workspace guides the seller until every required obligation is resolved.

That gives Verifund a consistent fulfillment experience for physical goods, digital products, and professional services—even when buyers and sellers interact with their agents through different messaging platforms.
