# Jira Cloud REST endpoint cheat sheet

Curated paths beyond the 10 ergonomic scripts. Use with `jira_api.py METHOD PATH [--body '{...}'] [--query k=v]`.

## Identity / workspace

| Op | Method + path |
|---|---|
| Current user | `GET /rest/api/3/myself` |
| Server info | `GET /rest/api/3/serverInfo` |
| Find user by email | `GET /rest/api/3/user/search?query=<email>` |
| Get user by accountId | `GET /rest/api/3/user?accountId=<id>` |

## Issues — beyond the ergonomic scripts

| Op | Method + path |
|---|---|
| Update issue fields | `PUT /rest/api/3/issue/{key}` body `{"fields": {...}}` |
| Delete issue | `DELETE /rest/api/3/issue/{key}` |
| Get edit metadata (which fields are editable) | `GET /rest/api/3/issue/{key}/editmeta` |
| Get create metadata for a project | `GET /rest/api/3/issue/createmeta/{projectKey}/issuetypes` |
| Get available transitions | `GET /rest/api/3/issue/{key}/transitions` |
| Issue changelog (history) | `GET /rest/api/3/issue/{key}/changelog` |
| Issue properties | `GET /rest/api/3/issue/{key}/properties` |
| Bulk fetch issues | `POST /rest/api/3/issue/bulkfetch` body `{"issueIdsOrKeys": [...]}` |

## Comments

| Op | Method + path |
|---|---|
| List comments | `GET /rest/api/3/issue/{key}/comment` |
| Get one comment | `GET /rest/api/3/issue/{key}/comment/{commentId}` |
| Update comment | `PUT /rest/api/3/issue/{key}/comment/{commentId}` body `{"body": <ADF>}` |
| Delete comment | `DELETE /rest/api/3/issue/{key}/comment/{commentId}` |

## Attachments

| Op | Method + path |
|---|---|
| List attachments on issue | `GET /rest/api/3/issue/{key}?fields=attachment` |
| Get attachment metadata | `GET /rest/api/3/attachment/{id}` |
| Download attachment content | `GET /rest/api/3/attachment/content/{id}` (binary) |
| Upload attachment (multipart) | `POST /rest/api/3/issue/{key}/attachments` header `X-Atlassian-Token: no-check`, multipart file form — easier via `curl` directly than `jira_api.py` |

## Issue linking

| Op | Method + path |
|---|---|
| List link types | `GET /rest/api/3/issueLinkType` |
| Create link | `POST /rest/api/3/issueLink` body `{"type": {"name": "Blocks"}, "inwardIssue": {"key": "ABC-1"}, "outwardIssue": {"key": "ABC-2"}}` |
| Get link by id | `GET /rest/api/3/issueLink/{id}` |
| Delete link | `DELETE /rest/api/3/issueLink/{id}` |

## Worklogs (time tracking)

| Op | Method + path |
|---|---|
| List worklogs | `GET /rest/api/3/issue/{key}/worklog` |
| Add worklog | `POST /rest/api/3/issue/{key}/worklog` body `{"timeSpent": "2h", "comment": <ADF>}` |
| Update worklog | `PUT /rest/api/3/issue/{key}/worklog/{id}` |
| Delete worklog | `DELETE /rest/api/3/issue/{key}/worklog/{id}` |

## Watchers, votes, mentions

| Op | Method + path |
|---|---|
| Add watcher | `POST /rest/api/3/issue/{key}/watchers` body `"<accountId>"` (note: bare quoted string, not object) |
| Remove watcher | `DELETE /rest/api/3/issue/{key}/watchers?accountId=<id>` |
| Get watchers | `GET /rest/api/3/issue/{key}/watchers` |
| Vote | `POST /rest/api/3/issue/{key}/votes` |

## Projects

| Op | Method + path |
|---|---|
| Project search | `GET /rest/api/3/project/search?query=<q>` |
| Get one project | `GET /rest/api/3/project/{key}` |
| Project components | `GET /rest/api/3/project/{key}/components` |
| Project versions | `GET /rest/api/3/project/{key}/versions` |
| Project roles | `GET /rest/api/3/project/{key}/role` |
| Project statuses by issuetype | `GET /rest/api/3/project/{key}/statuses` |

## Boards & sprints (Agile API — `/rest/agile/1.0/`)

| Op | Method + path |
|---|---|
| List boards | `GET /rest/agile/1.0/board?projectKeyOrId=<key>` |
| Board configuration | `GET /rest/agile/1.0/board/{id}/configuration` |
| Issues on a board | `GET /rest/agile/1.0/board/{id}/issue` |
| Backlog (scrum only) | `GET /rest/agile/1.0/board/{id}/backlog` |
| List sprints (scrum only) | `GET /rest/agile/1.0/board/{id}/sprint?state=active,future` |
| Issues in a sprint | `GET /rest/agile/1.0/sprint/{id}/issue` |
| Create sprint | `POST /rest/agile/1.0/sprint` body `{"name": "...", "originBoardId": <id>, "startDate": "...", "endDate": "..."}` |
| Move issues to sprint | `POST /rest/agile/1.0/sprint/{id}/issue` body `{"issues": ["ABC-1", "ABC-2"]}` |
| Move issues to backlog | `POST /rest/agile/1.0/backlog/{boardId}/issue` |

## Workflows & statuses

| Op | Method + path |
|---|---|
| Workflow schemes | `GET /rest/api/3/workflowscheme` |
| Statuses across workspace | `GET /rest/api/3/statuses` |
| Issue types across workspace | `GET /rest/api/3/issuetype` |
| Priorities | `GET /rest/api/3/priority` |
| Resolutions | `GET /rest/api/3/resolution` |

## Custom fields

| Op | Method + path |
|---|---|
| List all fields | `GET /rest/api/3/field` |
| Custom field options | `GET /rest/api/3/field/{fieldId}/option` |

## Admin (require workspace-admin permission)

| Op | Method + path |
|---|---|
| Create project | `POST /rest/api/3/project` |
| Update project | `PUT /rest/api/3/project/{key}` |
| Delete project | `DELETE /rest/api/3/project/{key}` |
| Project permissions | `GET /rest/api/3/project/{key}/permissionscheme` |
| User search (admin scope, returns more fields) | `GET /rest/api/3/users/search?startAt=0&maxResults=50` |

If the user doesn't have admin, these return 401/403 — surface the error transparently.
