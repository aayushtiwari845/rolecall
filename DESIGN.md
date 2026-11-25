---
name: Rolecall
description: Fresh tech roles, called out for you. A live scorecard of early-career roles, each match scored with its reasons.
colors:
  bg: "#f3f7f2"
  panel: "#ffffff"
  panel-2: "#e9f0e9"
  rule: "#d2ded4"
  rule-strong: "#a6bcab"
  ink: "#0b1a11"
  ink-2: "#33473b"
  ink-3: "#55695d"
  amber: "#f4c430"
  amber-ink: "#1c1500"
  amber-text: "#7a5600"
  red: "#c11f34"
  green: "#0c7440"
  pen: "#1d4fd8"
  board: "#0a1d14"
  board-2: "#10291d"
  board-rule: "#234634"
  chalk: "#eef4ec"
  chalk-2: "#a7c0b0"
  bg-dark: "#08160f"
  panel-dark: "#0d2017"
  panel-2-dark: "#112a1e"
  rule-dark: "#1d3a2b"
  rule-strong-dark: "#2c5541"
  ink-2-dark: "#b2c7b9"
  ink-3-dark: "#8aa394"
  red-dark: "#ff6168"
  green-dark: "#45dd8c"
  pen-dark: "#8fb2ff"
  board-dark: "#061109"
  board-2-dark: "#0c1f15"
typography:
  scoreboard:
    fontFamily: "Big Shoulders, Archivo, sans-serif"
    fontSize: "clamp(4.5rem, 10vw, 8rem)"
    fontWeight: 800
    lineHeight: 0.85
    letterSpacing: "-0.01em"
    fontFeature: "\"tnum\" 1, \"lnum\" 1"
    fontVariation: "\"opsz\" 72"
  display:
    fontFamily: "Big Shoulders, Archivo, sans-serif"
    fontSize: "clamp(3.5rem, 7vw, 5.5rem)"
    fontWeight: 800
    lineHeight: 0.85
    letterSpacing: "-0.01em"
    fontVariation: "\"opsz\" 72"
  headline:
    fontFamily: "Big Shoulders, Archivo, sans-serif"
    fontSize: "clamp(2.75rem, 5vw, 3.75rem)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "-0.01em"
  score:
    fontFamily: "Big Shoulders, Archivo, sans-serif"
    fontSize: "2.6rem"
    fontWeight: 800
    lineHeight: 0.85
    fontFeature: "\"tnum\" 1, \"lnum\" 1"
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.375
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\" 1, \"lnum\" 1"
  body-lead:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.625
  label:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    letterSpacing: "0.08em"
    fontVariation: "\"wdth\" 88"
rounded:
  toggle: "3px"
  sm: "4px"
  md: "6px"
  full: "9999px"
spacing:
  gutter: "16px"
  gutter-md: "24px"
  row: "16px"
  row-md: "20px"
  section: "64px"
  section-md: "96px"
  container: "1240px"
  container-wide: "1400px"
components:
  button-primary:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.md}"
    padding: "0 24px"
    height: "48px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-outline-hover:
    backgroundColor: "{colors.panel-2}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-board:
    backgroundColor: "transparent"
    textColor: "{colors.chalk}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  toggle:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.toggle}"
    padding: "0 10px"
    height: "32px"
  toggle-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.bg}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
  scoreboard:
    backgroundColor: "{colors.board}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.md}"
  job-row:
    textColor: "{colors.ink}"
    padding: "16px 0"
  toast:
    backgroundColor: "{colors.board}"
    textColor: "{colors.chalk}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
---

# Design System: Rolecall

## Overview

**Creative North Star: "The Live Innings"**

Rolecall is a cricket scoreboard and a scorer's book. The scoreboard is the public face: a pitch-black green panel with chalk numerals set huge in a condensed sports face, counting the open index live. The scorer's book is where the user works: a cool white page with a double green margin rule down the left, every entry written on a hairline. Every role is a row of hard numbers (match score, level, pay, posted age), and state is marked the way a scorer marks it, by hand: a blue pen ring circles a saved score, a red strike runs through a dismissed or rejected role.

Density is high and tabular. Rows, not cards; rules, not boxes. Numerals carry the hierarchy, so headings and scores share one condensed uppercase voice while reading text stays in a plain, slightly narrowed grotesque. Colour is semantic before it is decorative: amber is the one call to action and the active marker, green is runs (strong fits, offers, live), red is wickets (warnings, dismissals, rejections). Dark mode is the stadium at night; the scoreboard panel stays dark in both themes.

The build refuses the job-board defaults: no logo-tile card grid, no pill chips, no search-bar hero.

**Key Characteristics:**
- Two materials: the dark scoreboard (`.board`, dark in both themes) and the ruled scorebook page.
- Lists are ruled rows sharing one column order: score, role and reasons, level and pay, actions.
- Condensed Big Shoulders numerals and uppercase headings; Archivo for everything read.
- Tabular, lining figures everywhere, set globally on `body`.
- State marked by hand: pen ring for saved, red strike for dismissed and rejected.
- Motion is a scoreboard flip, a ball rolling in from the left, a ring being drawn; all collapse under reduced motion.

## Colors

A green-tinted neutral scale with one amber signal and a strict red/green scoring pair; every neutral leans toward pitch green, never pure grey.

### Primary
- **Scoreboard Amber** (`amber`): the only call-to-action fill ("Get my scorecard"), the active-nav underline, focus outline, caret, text selection and drag-over highlight. Text on it is always **Stump Black** (`amber-ink`).
- **Bat Bronze** (`amber-text`): amber as readable text on the light page (pay figures, active mobile-nav icon). In dark mode it resolves to Scoreboard Amber itself.

### Secondary
- **Runs Green** (`green`, `green-dark`): strong fits (match score 75 and above), reason bullets, the Offer column, live dots.
- **Wicket Red** (`red`, `red-dark`): warnings in a row, the dismiss strike, rejected and withdrawn roles, the Rejected column, error toasts, closed postings.

### Tertiary
- **Scorer's Pen Blue** (`pen`, `pen-dark`): the hand-drawn ring around a saved role's score and the saved bookmark icon. Nothing else.

### Neutral
- **Scorebook Page** (`bg`, `bg-dark`): page background; in light mode carries the double margin rule.
- **Sheet White** (`panel`, `panel-dark`): raised working surfaces (inputs, alternating landing bands, chat blocks, tracker slips).
- **Outfield Wash** (`panel-2`, `panel-2-dark`): hover fills, the focused-row band, skeletons, tracker lanes.
- **Hairline Green** (`rule`, `rule-dark`) and **Boundary Rule** (`rule-strong`, `rule-strong-dark`): row dividers and section borders; the stronger rule outlines inputs, outline buttons and toggles. In light mode row ruling is darkened to a fixed green hairline (#b9cfbf) and the margin rule is #b7ccbc, so the ruling reads as printed lines.
- **Pitch Ink** (`ink`), **Scorer's Graphite** (`ink-2`, `ink-2-dark`), **Faded Pencil** (`ink-3`, `ink-3-dark`): primary, secondary and tertiary text. In dark mode `ink` takes the chalk value.
- **Night Board** (`board`, `board-2`, `board-rule`, and dark variants): the scoreboard panel, its numeral plates and its plate seams; also the default toast.
- **Chalk** (`chalk`) and **Weathered Chalk** (`chalk-2`): numerals and labels on the board.

### Named Rules
**The Runs and Wickets Rule.** Green means a good outcome, red means a dismissal or warning. Neither is ever used as decoration, brand colour or category coding.

**The One Amber Rule.** Amber marks the single primary action and the current position (active nav, focus, selection). One amber-filled button per view region.

**The Neutrals Are Pitch Rule.** Every neutral is tinted toward green (hue around 140 to 155). Do not introduce a pure grey.

## Typography

**Display Font:** Big Shoulders (variable, `opsz` 72), falling back to Archivo
**Body Font:** Archivo (variable, with `wdth` axis), falling back to ui-sans-serif, system-ui

**Character:** A tall, condensed stadium face for every number and heading, against a sturdy, slightly narrowed grotesque for reading. The display face is always uppercase and extra-bold; the text face never is, except in labels.

### Hierarchy
- **Scoreboard** (800, 4.5rem to 8rem, 0.85): the lead count on the board plate; secondary plates 3.25rem to 5.25rem.
- **Display** (800, 3.5rem to 5.5rem, 0.85, uppercase): the landing headline, max 13ch.
- **Headline** (800, 2.75rem to 3.75rem, 0.9, uppercase): section headings and page heads (page heads 2.75rem to 3.5rem); 14 to 18ch measure.
- **Score** (800, 2.6rem in rows, 1.75rem compact, 4.5rem on job detail): the match number, centred over a small "match" label. Smaller score-face runs (1.25rem to 2rem) set inline counts, feature names and tracker column totals.
- **Title** (600, 1.0625rem, snug): a role's title in a row; the link underlines in amber on hover.
- **Body** (400, 0.875rem, 1.5): row metadata, reasons (0.8125rem), descriptions. Landing lead copy uses 1.125rem at 1.625, capped at 58ch; long prose caps at 60 to 68ch.
- **Label** (600, 0.6875rem, 0.08em tracking, uppercase, `wdth` 88): plate captions, field labels, seniority in a row, tracker column names, board status line.

### Named Rules
**The Tabular Everything Rule.** `tnum` and `lnum` are on globally; numbers in any column must align digit for digit.

**The Numerals Speak First Rule.** On any row or board the biggest thing is a number, not a word.

## Layout

A single centred column (max 1240px; 1400px for wide app views) with 16px gutters, 24px from `md`. Landing sections step in 64px, 96px from `md`, alternating Scorebook Page and Sheet White bands separated by a top rule. The landing first viewport is a 2fr/1fr grid from `lg`: the board, headline and actions on the left, the "Just posted" ruled list on the right.

Lists are the core layout: a three-column row grid (`auto | 1fr | auto`) collapsing to two columns on mobile, where level, pay and actions drop beneath. Rows are 16px tall-padding, 20px from `md`, 12px compact. Definition-style lists (features, settings) use a fixed 16rem term column against a prose column. The tracker is the one horizontally scrolling board: six lanes at a 1080px minimum.

App chrome: a 56px sticky header on a 90% translucent page colour with backdrop blur, and below `md` a five-item fixed bottom nav, safe-area aware.

## Elevation & Depth

Flat by default. Depth comes from the two materials (dark board against light page) and from rules, not from shadows. The board carries a 1px inset top highlight like a painted edge; its numeral plates add a short drop to sit hung on the board. Floating, transient things lift: the chat composer, toasts, and a tracker slip on hover.

### Shadow Vocabulary
- **Board edge** (`box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04)`): on the scoreboard panel.
- **Hung plate** (`box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04), 0 2px 6px rgb(0 0 0 / 0.35)`): a numeral plate on the board.
- **Slip lift** (`box-shadow: 0 4px 14px rgb(0 0 0 / 0.12)`): tracker slip on hover, signalling it can be dragged.
- **Composer float** (`box-shadow: 0 6px 20px rgb(0 0 0 / 0.15)`): the sticky chat composer.
- **Toast float** (`box-shadow: 0 8px 24px rgb(0 0 0 / 0.35)`): toasts.

### Named Rules
**The Rules Not Shadows Rule.** Rows and sections separate with 1px rules. A shadow appears only on something that floats over content or can be picked up.

## Shapes

Barely softened rectangles. Controls, panels and the board use a 6px radius (`md`); small selects and notes fields 4px; toggles a near-square 3px. Full rounding is reserved for status dots, reason bullets, avatars and the spinner. Borders are 1px hairlines; the dismiss strike is a 2px red line and the pen ring a 2.6px round-capped stroke, the only deliberately hand-drawn forms in the system.

## Components

### Buttons
Firm and plain, sized to a strict height scale.
- **Shape:** gently squared (6px), heights 32 / 40 / 48px with 12 / 16 / 24px side padding.
- **Primary:** Scoreboard Amber fill, Stump Black semibold text, trailing arrow icon. Hover brightens 5%, active dims 5%.
- **Outline:** Boundary Rule border, ink text, Outfield Wash on hover. The default variant.
- **Ghost:** no border, Scorer's Graphite text, ink and Outfield Wash on hover. Also used as an inline text link with an arrow.
- **Danger:** red border at 50% and red text, red at 10% on hover.
- **Board:** for use on the dark board: board-rule border, chalk text, board-2 on hover.
- **Icon buttons:** 36px square, 6px radius, 18px line icon, Outfield Wash on hover; the dismiss icon hovers to red on a red wash.
- **Focus:** a 2px amber outline at 2px offset, globally.

### Toggles
The build's replacement for chips: squared option buttons in a wrapping set.
- **Style:** 32px high, 3px radius, Boundary Rule border, Scorer's Graphite text.
- **State:** on inverts to an ink fill with page-colour text; `aria-pressed` carries state.

### Inputs / Fields
- **Style:** 40px, Sheet White fill, Boundary Rule border, 6px radius, amber caret, Faded Pencil placeholder.
- **Focus:** border turns amber.
- **Field:** a label-style caption above, an optional small hint right-aligned on the same baseline.

### Navigation
- **Desktop:** text links at 14px, Scorer's Graphite, active in semibold ink with a 3px amber bar sitting on the header's bottom rule. A live green dot and a score-face "new today" count sit at the right.
- **Mobile:** fixed bottom bar of five icon-over-label items at 11px; active item in ink with an amber icon.

### Job Row (signature)
One role as a scorecard row. Score on the left (green at 75 and above, ink at 55 and above, Faded Pencil below), then the title, a metadata line of company, place and posted age joined by middots, and up to three green-bulleted reasons and two red-bulleted warnings. Right column: seniority label and pay in Bat Bronze, then save, dismiss and open icon buttons. A keyboard-focused row gets an Outfield Wash band that bleeds 12px past the column. Saved draws the pen ring around the score; dismissed fades to 40% and a red strike draws left to right across the row.

### Scoreboard (signature)
The dark board, 6px radius, divided into numeral plates by board-rule seams rather than gaps. A status strip on top (live dot, crawl age, company count) in chalk-2 labels; plates of chalk numerals with label captions beneath; a lower strip of smaller counts in running text. Numerals flip in when data arrives. The same board material frames the closing call to action and the default toast.

### Ruled List
Any list of entries is a stack with a 1px top rule between items (`.ruled`), usually bounded by rules top and bottom. "Just posted" sets a score-face posted-age column (2.75rem) against title and metadata, each entry rolling in from the left.

### Tracker Slip
Tracker lanes are Outfield Wash columns with a label-style name (Offer in green, Rejected in red) and a score-face count. Entries are draggable slips: Sheet White, hairline border, 6px radius, 12px padding, lifting on hover. Rejected and withdrawn titles are struck through in a 2px red line. This is the only card form in the system, earned by drag and drop.

### Empty and Loading
Empty states are a score-face uppercase line between two rules with a short note beneath. Loading is skeleton rows in Outfield Wash that match the row layout, or a small ring spinner.

## Do's and Don'ts

### Do:
- **Do** set every count, score and age in the score face with tabular figures, and let it be the largest element in its row or plate.
- **Do** build lists as ruled rows with a shared column order; reach for a card only when the entry is physically moved (the tracker slip).
- **Do** keep the scoreboard panel dark (`board`) in both themes, with chalk numerals and board-rule seams.
- **Do** mark saved with the pen ring and dismissed or rejected with a red strike, never with a badge.
- **Do** keep amber to the primary action, the current position and focus.
- **Do** honour reduced motion: every animation collapses to 1ms and rests in its visible state (no fill-mode start frames).

### Don't:
- **Don't** build a card grid with logo tiles, pill chips or a search-bar hero.
- **Don't** use green or red for anything but runs and wickets.
- **Don't** introduce pure greys or a second accent hue.
- **Don't** separate rows with shadows or gaps where a 1px rule will do.
- **Don't** set reading text in the score face or in uppercase; uppercase belongs to the score face and to labels.
- **Don't** put a small uppercase label above a heading as a kicker; labels caption numerals, fields and columns.
