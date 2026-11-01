# Getting started with bibliograph

This guide is for researchers who want to use bibliograph with Claude Desktop. It
assumes no programming and no command line. If you are a developer, or you use
an AI app other than Claude Desktop, see the [README](../README.md) instead.

## What bibliograph does

bibliograph lets Claude search the catalogues Japan studies depends on, directly:
the National Diet Library (its catalogue, national bibliography, magazine
index, Digital Collections and full text), the WARP web archive, CiNii
Research, J-STAGE, the Korea Citation Index and Open Access Korea, OpenAlex,
Semantic Scholar and Crossref, plus a Japanese name
dictionary and the NDL's name authorities. Without it, Claude reaches
Japanese scholarship only through the open web and English-language indexes.

Every answer says what was searched, how the terms were matched, and what the
source does not cover, so "nothing found" means something. If you choose a
receipts folder, each search is also recorded there, so a search behind a
footnote can be named and run again.

## What you need

- **Claude Desktop** on Windows, macOS or Linux.
- **An internet connection.** On first launch bibliograph sets itself up, which
  needs a download and may take a minute or two.
- Nothing else. You do not need Python or any other software.

## 1. Install

1. Go to the [bibliograph releases page](https://github.com/ckgerteis/bibliograph-mcp/releases)
   and download the file ending in **`.mcpb`** from the latest release.
2. Open Claude Desktop, go to **Settings → Extensions**, and install the file
   you downloaded (you can also drag the file onto the Extensions page).
3. Claude Desktop shows a short settings form. **Every field is optional**, and
   you can leave them all blank and come back later. What each one does is
   explained under *Optional settings* below.
4. Make sure the extension is switched on, then quit Claude Desktop completely
   and open it again.

## 2. Check that it works

Start a new conversation and ask:

> Use bibliograph to search CiNii for 産業遺産 and tell me how many records came back.

Claude should call a tool named `cinii_search_all` and report a number. If you
want to see everything bibliograph has loaded, ask:

> Run bibliograph_status.

It lists each source with its version. Nothing should appear under
"skipped".

## 3. Build the name dictionary (once)

The name tools (turning "Sato Taro" into 佐藤太郎, finding the reading of a
kanji name, checking NDL name headings, glossing a Japanese term) read a
dictionary that is built on your own computer the first time. Ask:

> Check the bibliograph names index.

Claude will tell you it is not built yet, where it will be stored, and what
it needs to download. When you agree, it builds in the background:

- about **25 MB** is downloaded, from the EDRDG dictionaries (JMnedict, JMdict,
  KANJIDIC2) as packaged by the jmdict-simplified project;
- it takes about **one to two minutes**;
- it uses about **185 MB** of disk space.

Ask Claude to check again after a couple of minutes. When it reports the
index as built, the name tools are ready. You only do this once.

One name tool, `gloss_archaic` (classical and archaic senses from Wiktionary),
needs an extra dataset that this step does not fetch; the README explains it.

## Optional settings

You can change these at any time in **Settings → Extensions → bibliograph**.

| Setting | What it gives you | How to get it |
|---|---|---|
| CiNii application ID | Researcher Numbers (研究者番号) for Japanese scholars. Every other CiNii search works without it. | Register free at the [CiNii Web API developer registration](https://api.ci.nii.ac.jp/en/). |
| OpenAlex email | Faster, more reliable OpenAlex searches. | Any email address you use. |
| OpenAlex API key | Not needed for normal use. | Leave blank. |
| Semantic Scholar API key | Semantic Scholar searches that are not slowed by other users. | Free: use "Request an API key" on the [Semantic Scholar API page](https://www.semanticscholar.org/product/api). |
| Receipts folder | A record of every search: what was asked, of which source, when, and what came back. Useful for a methods note or a research-ethics file. | Choose any folder. Leave blank for no receipts. |
| Receipt session | A label (for example `my-article-2026`) stamped on each receipt, so a project's searches can be told apart. | Any short name. |
| Sources to load | Load only some sources, for example `ndl,cinii,jstage`. | Leave blank to load all. |

Keys you enter are stored by Claude Desktop, not in bibliograph's files, and bibliograph
never includes them in its answers or receipts.

## The NDL's request to continuous users

The National Diet Library asks people who use its Search API continuously to
tell it who they are and how they use it, through its own online form (see
section 17 of the NDL Search API help page,
<https://ndlsearch.ndl.go.jp/help/api>). This is your own arrangement with
the NDL; bibliograph cannot make it for you, but it does show whether you have
recorded one.

Until you have, NDL catalogue answers carry a note saying no notification
is recorded. The searches still work. The NDL full-text tools are not
affected: NDL Lab asks for no application for non-commercial use.

To record that you have filed:

1. Open the notices folder. On Windows, press **Win + R**, type `%APPDATA%`
   and press Enter; in the folder that opens, create a folder named `bibliograph`,
   and inside it a folder named `notices` (skip whichever already exist). On
   macOS or Linux the folder is `~/.config/bibliograph/notices`.
2. In that folder, create a plain text file named
   `NDL-API-NOTIFICATION.txt` (Notepad or TextEdit in plain-text mode is
   fine). Write in it the date you filed and what you declared.
3. Restart Claude Desktop.

The file must not be empty.

## If something goes wrong

**The bibliograph tools do not appear.** Check that the extension is switched on
under Settings → Extensions, then quit Claude Desktop completely (not just
close the window) and open it again. The first launch after installing can
take a minute or two while bibliograph sets itself up.

**A name tool says `INDEX_MISSING`.** The name dictionary is not built yet; see
step 3.

**An NDL search is slow or times out.** The NDL limits how fast it can be
asked, and bibliograph keeps to one request a second. A timeout usually means the
NDL is busy, not that nothing exists. Wait a little and try once more.

**A WARP request is slow.** That is deliberate: WARP asks users not to automate
heavy access, so bibliograph fetches one archived page at a time, a few seconds
apart.

**CiNii finds nothing for an author written in romaji.** Search the author in
kanji. Ask Claude to find the kanji forms first with `name_query_variants`
or `name_authority`.

**An OpenAlex or Semantic Scholar result is a book review, not the book.**
Those indexes sometimes hold only the reviews of a monograph. The result's
record type says `review`; look for the book in CiNii or the NDL instead.

## Removing bibliograph

Uninstall it under **Settings → Extensions**. The name dictionary stays in
your user folder (`bibliograph-names` under your local application data) until you
delete it, and your receipts stay wherever you chose to keep them.

## Getting help

Report a problem or ask a question on the
[issues page](https://github.com/ckgerteis/bibliograph-mcp/issues). Please do not
paste API keys into an issue.
