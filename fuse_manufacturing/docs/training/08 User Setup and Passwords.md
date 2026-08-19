# User Setup and Passwords

*Adding people, giving them access, and resetting a password — Fuse Manufacturing
administrator guide 08*

> This guide is for administrators. Unlike the other guides it covers the platform Fuse
> runs on rather than Fuse itself, so the screens look like standard ERPNext.

## Before you start

### How access works

Two separate things decide what somebody sees:

1. **A user account** — who they are, and how they sign in.
2. **Roles** — what they are allowed to do. A user with no roles can sign in and see
   nothing.

Fuse ships one role of its own, **Stock Controller**, which carries everything a shop
floor or stores person needs: stock movements, works orders, receiving, and read access
to the items and warehouses that come from Intacct.

### Who can do this

Only a System Manager. If you cannot see the Users list, you are not one.

## Adding a user

1. In the search bar at the top, type **User** and open the user list.
2. Click **+ Add User**.
3. Fill in:
   - **Email** — this is the username. Use a real address; the welcome email goes there.
   - **First Name** and **Last Name**.
4. Click **Save**.

> **Screenshot 1 — A new user record**
> *[to be inserted: the User form, Email and First Name filled in]*

5. Scroll to **Roles & Permissions** and tick the roles they need:
   - **Stock Controller** — shop floor, stores and receiving.
   - Add **Manufacturing User** as well if they will raise works orders.
6. Click **Save** again.

> **Screenshot 2 — The roles list with Stock Controller ticked**
> *[to be inserted: Roles & Permissions section]*

### A rule worth knowing

Give people access by **changing their roles**, not by editing what a document type
allows. Role assignments belong to the user and survive an upgrade. Permissions edited
on a document type are re-applied from the app every time Fuse is deployed, so a change
made that way disappears at the next release without warning.

## Setting a password

You do not type a password for somebody else, and you should not need to know theirs.

**Preferred — let them set it.** On the user record, use **Reset Password** from the
menu. They receive an email with a link and choose their own.

**If email is not working.** On the user record, open the menu and use **Set New
Password**. Give it to them in person and have them change it at first sign-in.

> **Screenshot 3 — The Reset Password menu item**
> *[to be inserted: the ⋯ menu open on a User record]*

## When somebody has forgotten their password

They can do it themselves, and this is the quickest route:

1. On the sign-in screen, click **Forgot Password**.
2. Enter the email address the account uses.
3. They receive a link and set a new password.

If no email arrives: check the spam folder, then check the address on the user record is
right. If it still does not arrive, the site's outgoing email is not configured — that is
a system issue, not a user one.

## When somebody leaves

**Disable the account; do not delete it.**

On the user record, untick **Enabled** and save. They can no longer sign in, and every
movement they recorded keeps their name against it. Deleting a user breaks the trail on
documents they raised.

> **Screenshot 4 — The Enabled checkbox**
> *[to be inserted: the top of the User form showing Enabled]*

## If something goes wrong

| What you see | What it means and what to do |
|---|---|
| The user signs in and the screen is empty | They have no roles. Add Stock Controller. |
| "Not permitted" opening a document | The role is missing that document. Check the role, not the document type. |
| A role that worked last week no longer does | A deploy re-applied the app's permissions. Tell your Fuse administrator rather than re-adding it by hand — it will only vanish again. |
| No password reset email | Check spam, then the address on the record, then the site's email settings. |
| Somebody needs access for one day | Add the role, then remove it. Do not share an account — the audit trail is per person. |

## Quick reference

| Task | Where |
|---|---|
| Add a user | Search → User → + Add User |
| Give access | The user record → Roles & Permissions |
| Reset a password | The user record → menu → Reset Password |
| Forgotten password | Sign-in screen → Forgot Password |
| Somebody leaves | The user record → untick Enabled |
