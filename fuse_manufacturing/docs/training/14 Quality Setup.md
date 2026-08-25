# Quality Setup

*Specifications, instruments, procedures and reviews — Fuse Manufacturing user guide 14*

## Before you start

### What this covers

Guide 13 is the daily job: check a batch, record what you found. This one is everything
behind it — what a batch is measured against, what the readings are taken on, how the work
is meant to be done, and what happens when it is not.

It is set up once by the people who own the product and the process, then referred to.
Nobody touches it during a shift.

### Where it lives

On Fuse Home, the **Quality** tile on the reference row opens the Quality page. Four cards:

| Card | What is in it |
|---|---|
| Inspection | Inspections, templates, parameters, parameter groups, measuring instruments |
| Procedures and goals | How the work is done, and what it is aiming at |
| Review and action | Reviews, meetings, corrective actions, customer feedback |
| Reports | Inspection summary, and a review of open actions |

> **Screenshot 1 — The Quality page**
> *[to be inserted: Fuse Quality workspace showing the four cards and the three shortcuts]*

## Specifications

### Parameters

A parameter is one thing that can be checked: *Visual condition*, *Channel count*,
*Operating temperature*. Write it once and use it on as many products as you like.

1. Quality page → **Quality Inspection Parameter** → **Add**.
2. Give it a name and a description. The description is what the person on the line reads,
   so say what "good" looks like rather than restating the name.

Group related parameters with a **Parameter Group** if you have enough of them to be worth
sorting.

### Templates

A template is the specification for a product: which parameters apply, and what each one
has to be.

1. Quality page → **Quality Inspection Template** → **Add**.
2. Name it after what it checks — *Incoming Camera Inspection*, *Assembled System Release*
   — not after the product code. One template usually covers several products.
3. Add a row per parameter and set the acceptance criteria:
   - **In words** — type what it must be. The reading has to match it to pass, so write
     the wording the inspector will use.
   - **Numeric** — tick Numeric and set a minimum and a maximum. The reading is compared
     against them automatically.

> **Screenshot 2 — A template with numeric and worded parameters**
> *[to be inserted: Quality Inspection Template with the parameter rows]*

### Putting a template on an item

1. Open the Item.
2. Set **Quality Inspection Template**.
3. Tick **Inspect before purchase**, **Inspect before delivery**, or both.

Those two ticks are what actually make Fuse ask. A template on an item with neither ticked
is a specification nobody is ever shown.

## Measuring instruments

Every instrument a reading is taken on belongs in the register, because a reading is only
evidence if the instrument was in calibration when it was taken.

1. Quality page → **Measuring Instruments** → **Add**.
2. Fill in:

| Field | What it is for |
|---|---|
| Instrument ID | What is written on the instrument itself |
| Type | pH meter, balance, thermometer, and so on |
| Status | Active, Out of Service, or Retired |
| Where it lives | So somebody can go and find it |
| Responsible | Who owns keeping it in calibration |
| Calibrated on / Calibration due | The interval, in dates |
| Certificate number and attachment | The evidence |

Fuse refuses an inspection recorded against an instrument whose calibration has passed its
due date, or that is marked Out of Service. That refusal is the control — it is why the
register is worth keeping properly rather than as a spreadsheet nobody opens.

> **Screenshot 3 — The instrument register**
> *[to be inserted: Fuse Measuring Instrument list, one Out of Service]*

## Procedures and goals

### Procedures

A procedure is how a piece of work is meant to be done, written down: *Goods Receiving and
Inspection*, *Production Release*, *Instrument Calibration*.

1. Quality page → **Quality Procedure** → **Add**.
2. Name it, then add one row per step. Keep the steps at the level someone could actually
   follow — four or five, not twenty.

Procedures can be nested, so a broad one can point at the detailed ones underneath it.

### Goals

A goal is what the process is aiming at, with a number against it.

1. Quality page → **Quality Goal** → **Add**.
2. Name the goal, choose how often it is measured, and link the procedure it belongs to.
3. Add one row per objective, each with a target and a unit — *Lines accepted first time,
   98, Percent*.

> **Screenshot 4 — A goal with its objectives**
> *[to be inserted: Quality Goal with two objectives and targets]*

## Review and action

### Reviews

At whatever interval the goal is set to, somebody records how it actually went.

1. Quality page → **Quality Review** → **Add**.
2. Choose the goal. Its objectives are pulled in with their targets.
3. Against each one, write what actually happened and why.

A review that only records the number is half a review. The sentence explaining the gap is
what the next person needs.

### Actions

A corrective action is what is being done about something that went wrong. A preventive
one is what is being done about something that nearly did.

1. Quality page → **Quality Action** → **Add**.
2. Choose Corrective or Preventive, and link the review or the feedback it came from.
3. Add a resolution row: what the problem is, and what is being done about it.
4. Close it when it has been verified — not when it has been agreed.

> **Screenshot 5 — A corrective action raised from a review**
> *[to be inserted: Quality Action showing the problem and resolution]*

### Customer feedback

1. Set up a **Feedback Template** with the questions you ask.
2. Record a **Quality Feedback** against the customer, with a rating and a comment per
   question.

Where the feedback shows something is ours to fix, raise an action from it. That is the
loop closing: the customer said something, it was traced, and something changed.

## How this hangs together

The chain worth being able to show an auditor runs in one direction:

**Specification** → **Inspection** (on a calibrated instrument) → **Rejection** →
**Review** → **Corrective action** → **Verified and closed**

Every step is a document, each one links to the last, and none of it depends on anybody
remembering. That is what makes the quality system evidence rather than intention.
