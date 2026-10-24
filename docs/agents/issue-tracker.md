# Issue tracker: GitHub

Issues and PRDs live in `heykay-47/google-classroom-downloader`.
Use the `gh` CLI with `--repo heykay-47/google-classroom-downloader`
to avoid accidentally targeting the upstream repository.

## Conventions

- Create: `gh issue create --repo heykay-47/google-classroom-downloader --title "..." --body-file -`
  Supply multiline bodies through a heredoc.
- Read: `gh issue view <number> --repo heykay-47/google-classroom-downloader --comments`
- Read metadata: `gh issue view <number> --repo heykay-47/google-classroom-downloader --json number,title,body,labels,comments`
- List: `gh issue list --repo heykay-47/google-classroom-downloader --state open --json number,title,body,labels`
  Add label or state filters as needed.
- Comment: `gh issue comment <number> --repo heykay-47/google-classroom-downloader --body "..."`
- Apply or remove labels: `gh issue edit <number> --repo heykay-47/google-classroom-downloader --add-label "..." --remove-label "..."`
- Close: `gh issue close <number> --repo heykay-47/google-classroom-downloader --comment "..."`

When a skill says "publish to the issue tracker", create a GitHub issue.
When it says "fetch the relevant ticket", read the issue, comments, and labels.
