# Creator Pack Editor (beta)

You film yourself talking. Creator Pack Editor turns those raw takes into a finished video on your own Mac: it hears your words, finds the story in what you said, cuts out the ums, the pauses and the repeats, adds captions and exports a video ready for Instagram or YouTube. Claude Code (the Claude app for your terminal) builds the story with you. Your footage never leaves your Mac.

This is the editing part of Creator Pack. Story Studio (ideas, story options and a script before you film) comes next.

## What you need

- A Mac with an Apple chip (M1 or newer).
- Claude Pro or Max, signed in to Claude Code. Get Claude Code at claude.com/claude-code.
- About 4 GB free space for the tools and the speech model, plus room for your videos.
- Internet for the one time setup (about 10 minutes). After that it works offline.

## Install

Pick one. The GitHub way is best: you get updates with one line.

### From the beta repo (you got a GitHub invite)

The repo is private, so first sign your Mac in to GitHub. Accept the invite email from GitHub, then in Terminal:

```
brew install gh
gh auth login
gh auth setup-git
```

(`gh auth login` asks a few questions: pick GitHub.com, HTTPS, and log in with a web browser. `gh auth setup-git` lets Claude Code use that login.)

Then open Claude Code and type these, one at a time:

```
/plugin marketplace add breakingcyclesexe-debug/creator-pack
/plugin install creator-pack@creator-pack
```

The second line opens the plugin's page in `/plugin`; choose install. Then type `/reload-plugins` (or quit and reopen Claude Code) and type `/creator-pack`.

If the first line says it can't find the repo: check you accepted the GitHub invite, and run `gh auth setup-git` again. If you don't use SSH keys with GitHub and it still fails, start Claude Code with `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1 claude` and try again.

### Getting updates

When there's a new version you'll hear from us. In Claude Code, type:

```
/plugin marketplace update creator-pack
```

That fetches the new version. Then `/reload-plugins`. (Same thing from Terminal: `claude plugin update creator-pack@creator-pack`.) Or turn on auto-update once and forget it: type `/plugin`, go to **Marketplaces**, pick **creator-pack** and turn on auto-update. (Auto-update is off by default for beta repos like this one; it works in the background because `gh auth setup-git` stored your login.)

Your videos stay where they are through every update, in `Movies/Creator Pack`.

### From the zip (if GitHub doesn't work for you)

Unzip `creator-pack-<version>.zip` somewhere you will keep it, for example your Documents folder. Then in Terminal:

```
claude --plugin-dir ~/Documents/creator-pack-<version>
```

Use that same line each time you want the pack (Claude Code only loads it when you start it this way). For an update, we send a new zip: unzip it and use the new folder name in that line.

## Your first video

1. In Claude Code, type `/creator-pack` (or just say "open the creator pack editor").
2. A page opens in your browser. The first time it shows **Get your Mac ready**: tick what's missing and press **Install**. Homebrew is the one thing you install yourself; the page shows the line to paste into Terminal (it asks for your Mac password).
3. Press **Open the editor**, drop in your takes (or pick them from your Mac), choose what it's for and press **Go**.
4. Leave Claude Code open. It builds the story while you wait, then the page cuts the video.

## What to expect

- Setup: about 10 minutes, once. The speech model is a 1.6 GB download, so that part is the slow one.
- The first time you open the pack, Claude Code spends about 30 seconds setting up its own helpers.
- Story: about a minute after you press Go, for a few minutes of footage.
- The cut: about 2 minutes for a short video. Longer footage takes longer.
- Every video gets checked for missing words, lip sync and clipped sentences before you see it. Anything worth a look is marked on the timeline.

## The chat

Each video has a chat. Ask for changes in plain words: "drop the bit about the weather", "start with the line about quitting", "less tight", "bigger captions". Claude Code makes the change and cuts a new version. Every version is kept, so you can go back.

Not in this version yet: music, titles, animations and your own fonts. Finish those in an editing app (the export works in any of them).

## Exporting

Press **Export** on the finished video. It goes to that video's own folder:

`Movies/Creator Pack/<your video>/Exports`

Next to it, **Footage** holds the clips you dropped in. **Open folder** on the page shows you the folder in Finder.

## When something goes wrong

**The page says "Claude isn't listening".** Claude Code stopped listening, or was closed. Open it again and type `/creator-pack`. Your videos are safe; it picks up where you left off.

**Setup says something is missing.** Press **Check again** after an install finishes. If one keeps failing, the page shows why under it. Homebrew always needs you to paste one line into Terminal yourself.

**"Python 3 is missing".** Install Homebrew (the line is on brew.sh), then run `brew install python` and open the pack again.

**The page won't open.** In Claude Code, ask "open the creator pack page". The page lives at a local address on your Mac only (it starts with `http://127.0.0.1`).

**Where are my files?** Everything is in `Movies/Creator Pack`. Each video has its own folder with Footage, References and Exports. Deleting the pack never deletes these.

## Feedback

This is a beta and your feedback shapes it. Tell us what confused you, what broke and what you wished it did. Reply to the beta invite email or DM us on Instagram. A screen recording or the video's name helps a lot.

## Beta limits

- Mac with an Apple chip only. No Windows yet.
- English works best. Other languages, Cantonese and Mandarin captions are early.
- Please don't share the pack. Your copy is for you.
