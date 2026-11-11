# Ama Da Flow WhatsApp → ClickUp: team guide

You can create ClickUp tasks, save ideas and post progress updates by sending a short message in one of the Ama Da Flow WhatsApp groups. A bot reads the message, does the work in ClickUp and replies in the group.

## 1. Which groups

The bot works in these Ama Da Flow groups:

- AmaDaFlow MARKETING team
- Website + Ai
- ADF - team workflow

Everything you send to the bot in these groups goes to the Ama Da Flow list in ClickUp.

## 2. How to use it

Start your message with one of three words followed by a colon: `task:`, `idea:` or `progress:`. The bot ignores all other messages in the group, so normal chat is safe.

### Create a task

```
task: Design the new Instagram carousel
```

The bot creates the task and replies with a link to it.

**Assign someone.** Add `@` and their name:

```
task: Prepare the client deck @victor
```

The bot shows you who it matched and asks you to confirm. If it can't find a name, it tells you.

**Add details.** The first line is the task title. Anything on the next lines (notes, links) goes into the task description:

```
task: Update the pricing page
Use the new prices from the sheet
https://example.com/pricing-sheet
```

### Save an idea

```
idea: Run a Ramadan bundle promo
```

The bot saves it in ClickUp tagged as an idea.

### Post a progress update

Paste the task link (or its ID), then your update:

```
progress: https://app.clickup.com/t/86abc123 Waiting for the client's photos
```

This adds your update as a comment on the task. You can also use the task name instead of the link. If more than one task matches the name, the bot asks you for the link.

**Change the status** by writing only the status as your update:

| You write | Status becomes |
| --- | --- |
| `progress: <link> in progress` (or `on progress`, `started`, `sedang dikerjakan`) | In progress |
| `progress: <link> done` (or `complete`, `finished`, `selesai`, `beres`) | Complete. The bot asks you to confirm first. |

### When the bot asks "yes or no"

Some requests need your OK first, like marking a task done. Reply in the same group within 15 minutes:

- **Yes:** `yes`, `ya`, `iya`, `ok` or `oke`
- **No:** `no`, `tidak`, `gak`, `batal` or `cancel`

If you have more than one request waiting, the bot lists them with a short code. Reply with the code, for example `yes 3f9a1c2b7e`.

Only you can answer your own requests. Someone else's "yes" does nothing.

### If something goes wrong

- **The bot replies with a code and says to retry.** Send `retry` plus that code, for example `retry 3f9a1c2b7e`.
- **The bot says to check ClickUp first.** The task may already have been created. Check ClickUp before retrying so you don't end up with a duplicate.
- **The bot doesn't reply at all.** Check that the message starts with `task:`, `idea:` or `progress:`, and that your number is registered (section 3).

### Quick tips

- Bold or italic formatting (`*task: ...*`) is fine.
- Keep task titles short. Put the long parts on the next lines.
- Photos, voice notes and stickers in the group are ignored. Send text.

## 3. How to register your number

The bot only responds to registered numbers. Messages from anyone else are ignored without a reply. You can't sign yourself up; the workflow admin adds you.

**To get registered, send the admin:**

1. Your name, written the way it appears in ClickUp
2. Your WhatsApp number with the country code, for example `62812xxxxxxx`
3. Which Ama Da Flow group(s) you're in

**Also make sure:**

- You've been added to the Ama Da Flow WhatsApp group you'll use.
- You're a member of the Ama Da Flow ClickUp workspace. Without that, others can't assign tasks to you with `@yourname`.

Once the admin confirms you're added, test it with something like `idea: test from <your name>` in your group. The bot should reply within a minute.

**If you change your WhatsApp number,** tell the admin. Your new number has to be registered again.
